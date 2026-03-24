from supabase import create_client, Client
from src.utils.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
from src.utils.logger import logger

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Supabase client initialized")
    return _client


def upsert(table: str, data: dict | list, on_conflict: str) -> list:
    client = get_client()
    rows = data if isinstance(data, list) else [data]
    result = client.table(table).upsert(rows, on_conflict=on_conflict).execute()
    return result.data


def insert(table: str, data: dict | list) -> list:
    client = get_client()
    rows = data if isinstance(data, list) else [data]
    result = client.table(table).insert(rows).execute()
    return result.data


def select(table: str, query: dict | None = None) -> list:
    client = get_client()
    q = client.table(table).select("*")
    if query:
        for col, val in query.items():
            q = q.eq(col, val)
    return q.execute().data


def update(table: str, match: dict, data: dict) -> list:
    client = get_client()
    q = client.table(table).update(data)
    for col, val in match.items():
        q = q.eq(col, val)
    return q.execute().data


def verify_connection() -> bool:
    try:
        client = get_client()
        client.table("markets").select("id").limit(1).execute()
        logger.info("Supabase connection verified")
        return True
    except Exception as e:
        logger.error(f"Supabase connection failed: {e}")
        return False
