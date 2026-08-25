"""Confirm your Zoho module + field API names.

"Opportunities" is a DISPLAY name; the API uses a module API name (usually
"Deals") and field API names (e.g. "Project_ID", not "Project ID"). This script
lists them so you can set ZOHO_MODULE and ZOHO_PID_FIELD correctly in .env, and
verify the field names hardcoded in src/zoho_client.py FIELD_MAP.

RUN (after ZOHO_* values are in .env):
  python scripts/inspect_zoho_module.py
  python scripts/inspect_zoho_module.py Deals     # inspect a specific module
"""
import sys

import requests

sys.path.insert(0, ".")
from src.config import get_config  # noqa: E402


def _access_token(cfg) -> str:
    resp = requests.post(
        f"{cfg.zoho_accounts_base}/oauth/v2/token",
        params={
            "refresh_token": cfg.zoho_refresh_token,
            "client_id": cfg.zoho_client_id,
            "client_secret": cfg.zoho_client_secret,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def main() -> int:
    from src.config import require_config

    cfg = get_config()
    require_config(cfg, {
        "ZOHO_CLIENT_ID": cfg.zoho_client_id,
        "ZOHO_CLIENT_SECRET": cfg.zoho_client_secret,
        "ZOHO_REFRESH_TOKEN": cfg.zoho_refresh_token,
    }, "section 2")
    token = _access_token(cfg)
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    if len(sys.argv) > 1:
        module = sys.argv[1]
        resp = requests.get(
            f"{cfg.zoho_api_base}/settings/fields",
            headers=headers, params={"module": module}, timeout=30,
        )
        resp.raise_for_status()
        print(f"\nFields in module '{module}' (api_name -> label):\n")
        for f in resp.json().get("fields", []):
            print(f"  {f['api_name']:<30} {f.get('field_label', '')}")
        print("\nSet ZOHO_PID_FIELD to whichever api_name holds your Project ID.")
    else:
        resp = requests.get(f"{cfg.zoho_api_base}/settings/modules",
                            headers=headers, timeout=30)
        resp.raise_for_status()
        print("\nModules (api_name -> label):\n")
        for m in resp.json().get("modules", []):
            print(f"  {m['api_name']:<30} {m.get('plural_label', '')}")
        print("\nFind the one labeled 'Opportunities' (or 'Deals'); put its "
              "api_name in ZOHO_MODULE.\nThen re-run:  "
              "python scripts/inspect_zoho_module.py <that_api_name>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
