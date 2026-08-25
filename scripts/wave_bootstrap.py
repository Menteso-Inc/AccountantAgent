"""Discover the Wave IDs you must put in .env.

Prints your business id and the income/sales account id used for invoice line
items, plus a sample of existing customers. Requires WAVE_API_TOKEN in .env and
a PAID Wave plan (Pro/Advisor) — free plans cannot authorize the API.

RUN:
  python scripts/wave_bootstrap.py
"""
import sys

import requests

sys.path.insert(0, ".")
from src.config import get_config  # noqa: E402

WAVE_ENDPOINT = "https://gql.waveapps.com/graphql/public"

QUERY = """
query {
  businesses(page: 1, pageSize: 10) {
    edges {
      node {
        id
        name
        accounts(page: 1, pageSize: 50) {
          edges { node { id name type { name value } subtype { name value } } }
        }
        customers(page: 1, pageSize: 10) {
          edges { node { id name email } }
        }
      }
    }
  }
}
"""


def main() -> int:
    from src.config import require_config

    cfg = get_config()
    require_config(cfg, {"WAVE_API_TOKEN": cfg.wave_api_token}, "section 3")
    resp = requests.post(
        WAVE_ENDPOINT,
        headers={
            "Authorization": f"Bearer {cfg.wave_api_token}",
            "Content-Type": "application/json",
        },
        json={"query": QUERY},
        timeout=45,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        print("Wave API error:", payload["errors"])
        print("If this says the token is unauthorized, confirm your Wave plan "
              "is Pro/Advisor and the token is a full-access token.")
        return 1

    for edge in payload["data"]["businesses"]["edges"]:
        biz = edge["node"]
        print(f"\nBUSINESS: {biz['name']}")
        print(f"  WAVE_BUSINESS_ID={biz['id']}")
        print("  --- income accounts (pick one for WAVE_INCOME_ACCOUNT_ID) ---")
        for a in biz["accounts"]["edges"]:
            node = a["node"]
            type_name = (node.get("type") or {}).get("value", "")
            if "INCOME" in str(type_name).upper():
                print(f"    WAVE_INCOME_ACCOUNT_ID={node['id']}   # {node['name']}")
        print("  --- existing customers (sample) ---")
        for c in biz["customers"]["edges"]:
            print(f"    {c['node']['id']}  {c['node']['name']}  {c['node'].get('email','')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
