"""
Root conftest: inject dummy env vars so config.py can be imported without a real .env.
All unit tests use these stubs — no network or DB calls are made.
"""
import os

# Must be set before any src.* imports (config.py reads them at module level)
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-key")
os.environ.setdefault("POLYMARKETSCAN_API_KEY", "fake-key")
os.environ.setdefault("FALCON_BEARER_TOKEN", "fake-token")
