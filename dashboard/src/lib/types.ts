export interface PortfolioState {
  strategy: "BASKET" | "SCALPER";
  initial_capital: number;
  current_capital: number;
  peak_capital: number | null;
  total_pnl: number;
  total_pnl_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  max_drawdown: number;
  consecutive_losses: number;
  is_circuit_broken: boolean;
  circuit_broken_until: string | null;
  requires_manual_review: boolean;
  open_positions: number;
  max_open_positions: number;
  updated_at: string;
}

export interface CopyTrade {
  id: string;
  strategy: "BASKET" | "SCALPER";
  signal_id: string | null;
  source_wallet: string | null;
  market_polymarket_id: string;
  market_question: string | null;
  market_category: string | null;
  direction: "YES" | "NO";
  outcome_token_id: string | null;
  entry_price: number;
  exit_price: number | null;
  shares: number;
  position_usd: number;
  pnl_usd: number | null;
  pnl_pct: number | null;
  status: "OPEN" | "CLOSED" | "CANCELLED";
  close_reason: string | null;
  opened_at: string;
  closed_at: string | null;
  is_paper: boolean;
  metadata: Record<string, unknown> | null;
}

export interface ConsensusSignal {
  id: string;
  basket_id: string;
  basket_category?: string | null;
  market_polymarket_id: string;
  market_question: string | null;
  direction: "YES" | "NO";
  outcome_token_id: string | null;
  consensus_pct: number;
  wallets_agreeing: number;
  wallets_total: number;
  window_start: string | null;
  window_end: string | null;
  price_at_signal: number | null;
  status: "PENDING" | "EXECUTED" | "EXPIRED" | "REJECTED";
  created_at: string;
  executed_at: string | null;
}

export type TimeFilter = "today" | "1w" | "1m" | "3m" | "1y" | "all";
