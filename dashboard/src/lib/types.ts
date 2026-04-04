export interface PortfolioState {
  id: number;
  initial_capital: number;
  current_capital: number;
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
  open_positions: number;
  max_open_positions: number;
  updated_at: string;
  run_id: number;
}

export interface PaperTrade {
  id: string;
  signal_id: string;
  market_id: string;
  direction: "YES" | "NO";
  entry_price: number;
  exit_price: number | null;
  shares: number;
  position_usd: number;
  pnl_usd: number | null;
  pnl_pct: number | null;
  status: "OPEN" | "CLOSED";
  close_reason: string | null;
  opened_at: string;
  closed_at: string | null;
  run_id: number;
  market_question?: string;
}

export interface Signal {
  id: number;
  market_id: string;
  signal_type: string;
  direction: "YES" | "NO";
  confidence: number;
  price_at_signal: number;
  divergence_score: number;
  momentum_score: number;
  smart_wallet_score: number;
  total_score: number;
  status: string;
  created_at: string;
  expires_at: string;
}

export interface MarketInfo {
  id: string;
  question: string;
  yes_price: number;
  no_price: number;
  volume_24h: number;
  end_date: string;
}

export type TimeFilter = "today" | "1w" | "1m" | "3m" | "1y" | "all";
