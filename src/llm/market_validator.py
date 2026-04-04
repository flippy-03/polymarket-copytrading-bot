"""
LLM Market Validator — asks Claude to evaluate whether a contrarian trade makes sense.

Fail-open by design: any API error, timeout, or parse failure allows the trade through.
The LLM is a quality filter, never a system bottleneck.
"""

import json
import os

import anthropic

from src.utils.config import LLM_ENABLED, LLM_MODEL
from src.utils.logger import logger

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


_PROMPT_TEMPLATE = """\
You are a prediction market analyst evaluating a contrarian trade signal from an automated bot.

## Market
Question: {question}
Resolves: {resolution_date}
Current YES price: {yes_price:.2f} | NO price: {no_price:.2f}

## Bot's Signal
Direction: {direction} (contrarian bet — fading the crowd)
Total score: {total_score:.1f}/100
Divergence score: {divergence_score:.1f} (whale herding + price velocity)
Momentum score: {momentum_score:.1f} (price pattern: {momentum_pattern})
Price velocity 1h: {velocity_1h:+.2%}

## Your Task
The bot detected whale herding (large traders piling into one side) aligned with a price \
spike, and wants to take the OPPOSITE side (contrarian mean-reversion).

Evaluate whether the bot's reasoning is sound:
1. Does a contrarian position make logical sense for this specific market?
2. Is this the type of market where mean-reversion is plausible (event-based, binary outcome)?
3. Or is the price move driven by genuine new information where following the crowd is correct?

REJECT if ANY of these apply:
- The question is ambiguous, subjective, or hard to resolve objectively
- The outcome is already nearly certain (one side >85%)
- This is a pure crypto price-target (BTC/ETH reach/dip/above/below $X by date) — these are driven by macro volatility, not herd manipulation
- The contrarian position contradicts publicly available facts or recent events
- The market is about counting/measuring something unpredictable (tweet counts, exact ranges)

Respond ONLY with valid JSON, no markdown:
{{"valid": true, "reasoning": "1-2 sentences explaining why the contrarian bet makes sense"}}
or
{{"valid": false, "reasoning": "1-2 sentences explaining why the bot's analysis is wrong"}}\
"""


def validate_trade_with_llm(
    question: str,
    resolution_date: str,
    yes_price: float,
    direction: str,
    total_score: float = 0,
    divergence_score: float = 0,
    momentum_score: float = 0,
    momentum_pattern: str = "unknown",
    velocity_1h: float = 0,
) -> tuple[bool, str]:
    """
    Returns (should_trade, reasoning).

    Calls Claude to evaluate whether the bot's contrarian signal is logically sound.
    Receives the full signal context (scores, pattern, velocity) so the LLM can
    reason about whether the bot's calculation makes sense.

    On any failure (API error, timeout, parse error): returns (True, "llm_unavailable")
    so the trade proceeds normally — fail open.
    """
    if not LLM_ENABLED:
        return True, "llm_disabled"

    no_price = round(1 - yes_price, 4)
    prompt = _PROMPT_TEMPLATE.format(
        question=question,
        resolution_date=resolution_date or "unknown",
        yes_price=yes_price,
        no_price=no_price,
        direction=direction,
        total_score=total_score,
        divergence_score=divergence_score,
        momentum_score=momentum_score,
        momentum_pattern=momentum_pattern,
        velocity_1h=velocity_1h,
    )

    try:
        client = _get_client()
        message = client.messages.create(
            model=LLM_MODEL,
            max_tokens=128,
            timeout=8.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        result = json.loads(raw)
        valid = bool(result.get("valid", True))
        reasoning = str(result.get("reasoning") or result.get("reason") or "")[:300]
        level = "info" if not valid else "debug"
        getattr(logger, level)(f"LLM validation: valid={valid} reasoning={reasoning!r}")
        return valid, reasoning

    except anthropic.APITimeoutError:
        logger.warning("LLM validation timeout — failing open")
        return True, "llm_timeout"
    except anthropic.APIError as e:
        logger.warning(f"LLM API error — failing open: {e}")
        return True, "llm_api_error"
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"LLM response parse error — failing open: {e}")
        return True, "llm_parse_error"
    except Exception as e:
        logger.warning(f"LLM unexpected error — failing open: {e}")
        return True, "llm_error"
