"""Temporary diagnostic: inspect scalper_pool state."""
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import supabase_client as _db


def main() -> None:
    client = _db.get_client()

    print("=== Top 10 pool rows by entered_at desc ===")
    r = (
        client.table("scalper_pool")
        .select("wallet_address,run_id,status,entered_at")
        .order("entered_at", desc=True)
        .limit(10)
        .execute()
        .data
    )
    for x in r:
        rid = x.get("run_id")
        wa = x["wallet_address"][:10]
        st = x["status"]
        ts = (x.get("entered_at") or "")[:16]
        print(f"  run={rid!r:40} wallet={wa}.. status={st} entered={ts}")

    print("\n=== eq('run_id','b4a40e7d-...') query ===")
    target = "b4a40e7d-ac4b-40a2-adcd-8904134b8f42"
    r2 = (
        client.table("scalper_pool")
        .select("wallet_address,run_id,status")
        .eq("run_id", target)
        .execute()
        .data
    )
    print(f"  Count: {len(r2)}")
    for x in r2:
        print(f"    wallet={x['wallet_address'][:10]}.. status={x['status']}")

    print("\n=== Hex representation of first b4a40 row's run_id ===")
    # Find a row and compare bytes
    for x in r:
        if "b4a40e7d" in str(x.get("run_id", "")):
            rid = x["run_id"]
            print(f"  Stored run_id: {rid!r}")
            print(f"  Stored len: {len(rid)}")
            print(f"  Target:     {target!r}")
            print(f"  Target len: {len(target)}")
            print(f"  Equal:      {rid == target}")
            break


if __name__ == "__main__":
    main()
