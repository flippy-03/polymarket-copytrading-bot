"""
Status API — lightweight HTTP server for external monitoring (Openclaw, etc.)

Exposes GET endpoints that return JSON:
  /status          — services + portfolio summary
  /logs/collector  — last N lines of collector log
  /logs/signals    — last N lines of signal engine log
  /logs/trader     — last N lines of paper trader log

Runs on port 8765. No auth (internal VPS only — do NOT expose to internet without auth).
Start: python scripts/status_api.py
Or via systemd: polymarket-status-api.service
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from src.db import supabase_client as db
from src.utils.logger import logger

PORT = 8765
LOG_DIR = Path(__file__).parent.parent / "logs"

SERVICES = {
    "collector": "polymarket-collector",
    "signal_engine": "polymarket-signal-engine",
    "paper_trader": "polymarket-paper-trader",
}


def _service_status(service_name: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()  # "active" | "inactive" | "failed"
    except Exception:
        return "unknown"


def _tail_log(log_file: str, lines: int = 50) -> list[str]:
    path = LOG_DIR / log_file
    if not path.exists():
        return []
    try:
        with open(path, "r", errors="replace") as f:
            all_lines = f.readlines()
        # Strip ANSI color codes for clean output
        import re
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        return [ansi.sub("", l).rstrip() for l in all_lines[-lines:]]
    except Exception:
        return []


def _portfolio_stats() -> dict:
    try:
        client = db.get_client()
        state = client.table("portfolio_state").select("*").limit(1).execute().data
        if not state:
            return {}
        s = state[0]
        open_trades = client.table("paper_trades").select("id,direction,entry_price,position_usd,opened_at").eq("status", "OPEN").execute().data
        return {
            "current_capital": float(s.get("current_capital", 0)),
            "initial_capital": float(s.get("initial_capital", 1000)),
            "total_pnl": float(s.get("total_pnl", 0)),
            "total_pnl_pct": float(s.get("total_pnl_pct", 0)),
            "open_positions": int(s.get("open_positions", 0)),
            "total_trades": int(s.get("total_trades", 0)),
            "winning_trades": int(s.get("winning_trades", 0)),
            "losing_trades": int(s.get("losing_trades", 0)),
            "win_rate": float(s.get("win_rate", 0)),
            "max_drawdown": float(s.get("max_drawdown", 0)),
            "circuit_breaker": s.get("circuit_broken_until") is None,
            "open_trades": open_trades,
        }
    except Exception as e:
        return {"error": str(e)}


def _full_status() -> dict:
    services = {k: _service_status(v) for k, v in SERVICES.items()}
    all_running = all(v == "active" for v in services.values())
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "healthy": all_running,
        "services": services,
        "portfolio": _portfolio_stats(),
    }


class StatusHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default HTTP access logs

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip("/")

        if path == "/status" or path == "":
            self._send_json(_full_status())

        elif path == "/logs/collector":
            self._send_json({"lines": _tail_log("collector.log")})

        elif path == "/logs/signals":
            self._send_json({"lines": _tail_log("signal_engine.log")})

        elif path == "/logs/trader":
            self._send_json({"lines": _tail_log("paper_trader.log")})

        elif path == "/healthz":
            self._send_json({"ok": True})

        else:
            self._send_json({"error": "Not found"}, 404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), StatusHandler)
    logger.info(f"Status API running on port {PORT}")
    logger.info(f"  GET http://localhost:{PORT}/status")
    logger.info(f"  GET http://localhost:{PORT}/logs/collector")
    logger.info(f"  GET http://localhost:{PORT}/logs/signals")
    logger.info(f"  GET http://localhost:{PORT}/logs/trader")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Status API stopped")
