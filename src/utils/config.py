"""
Shared environment configuration.

Strategy-specific constants live in src/strategies/common/config.py.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Supabase ─────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
