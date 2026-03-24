"""
Leaderboard seeder: fetches the top 100 traders once per day,
enriches with wallet_profile stats, and upserts into watched_wallets.

Wallet type classification heuristics (v1):
- BOT:          win_rate > 0.80 AND total_trades > 500
- SMART_HUMAN:  win_rate > 0.60 AND total_trades < 200 AND total_pnl > 10_000
- HUMAN:        everything else with reasonable activity
"""

from datetime import datetime, timezone

from src.data.polymarketscan_client import PolymarketScanClient
from src.db import supabase_client as db
from src.utils.logger import logger


def _extract_win_rate(profile: dict) -> float:
    """Handle both win_rate field and wins/losses fields. Always returns 0.0-1.0."""
    if profile.get("win_rate") is not None:
        val = float(profile["win_rate"])
        # Normalize: some APIs return 0-100, we need 0-1
        return val / 100.0 if val > 1.0 else val
    wins = int(profile.get("wins") or 0)
    losses = int(profile.get("losses") or 0)
    total = wins + losses
    return wins / total if total > 0 else 0.0


def _extract_total_trades(profile: dict) -> int:
    return int(profile.get("total_trades") or profile.get("num_trades") or 0)


def _classify_wallet(profile: dict) -> str:
    win_rate = _extract_win_rate(profile)
    total_trades = _extract_total_trades(profile)
    total_pnl = float(profile.get("total_pnl") or 0)

    if win_rate > 0.80 and total_trades > 500:
        return "BOT"
    if win_rate > 0.60 and total_trades < 200 and total_pnl > 10_000:
        return "SMART_HUMAN"
    if total_trades > 0:
        return "HUMAN"
    return "UNKNOWN"


def _assign_tier(profile: dict, wallet_type: str) -> str:
    total_pnl = float(profile.get("total_pnl") or 0)
    win_rate = _extract_win_rate(profile)

    if wallet_type == "SMART_HUMAN" and total_pnl > 50_000:
        return "S"
    if (wallet_type in ("SMART_HUMAN", "BOT")) and (total_pnl > 10_000 or win_rate > 0.70):
        return "A"
    return "B"


def seed_leaderboard(limit: int = 100) -> int:
    """
    Fetch leaderboard + enrich each wallet with profile data.
    Upserts into watched_wallets. Returns number of wallets saved.
    """
    pms = PolymarketScanClient()
    saved = 0

    try:
        logger.info(f"Fetching leaderboard (top {limit})...")
        leaders = pms.get_leaderboard(limit=limit)
        logger.info(f"Got {len(leaders)} leaderboard entries")

        rows = []
        for entry in leaders:
            address = entry.get("wallet_address") or entry.get("address") or entry.get("wallet") or entry.get("user")
            if not address:
                continue

            try:
                profile = pms.get_wallet_profile(address)
            except Exception as e:
                logger.warning(f"Profile fetch failed for {address[:10]}...: {e}")
                profile = entry  # use leaderboard data as fallback

            wallet_type = _classify_wallet(profile)
            tier = _assign_tier(profile, wallet_type)

            row = {
                "wallet_address": address,
                "label": f"leaderboard_{address[:8]}",
                "tier": tier,
                "wallet_type": wallet_type,
                "win_rate": _extract_win_rate(profile) or None,
                "total_pnl": profile.get("total_pnl"),
                "total_trades": _extract_total_trades(profile) or None,
                "avg_position_size": profile.get("avg_position_size"),
                "is_active": True,
                "source": "polymarketscan",
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            rows.append(row)

        if rows:
            db.upsert("watched_wallets", rows, on_conflict="wallet_address")
            saved = len(rows)
            logger.info(
                f"Seeded {saved} wallets — "
                f"BOT:{sum(1 for r in rows if r['wallet_type']=='BOT')} "
                f"SMART_HUMAN:{sum(1 for r in rows if r['wallet_type']=='SMART_HUMAN')} "
                f"HUMAN:{sum(1 for r in rows if r['wallet_type']=='HUMAN')}"
            )

        return saved

    except Exception as e:
        logger.error(f"seed_leaderboard failed: {e}")
        return 0
    finally:
        pms.close()
