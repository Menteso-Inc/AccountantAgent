"""One-time helper: exchange a Zoho self-client grant token for a refresh token.

WHAT YOU NEED FIRST (docs/SETUP.md section 2):
  1. Go to https://api-console.zoho.com  ->  create a "Self Client".
  2. Note the Client ID and Client Secret.
  3. In the "Generate Code" tab, enter scope:  ZohoCRM.modules.READ,ZohoCRM.settings.READ
     pick a duration (e.g. 10 minutes), and generate a grant code.
  4. Run this script and paste the values when prompted (or pass as args).

USAGE:
  python scripts/get_zoho_refresh_token.py <client_id> <client_secret> <grant_code> [dc]
  # dc defaults to "com". Use in / eu / com.au / jp for other data centers.
"""
import sys

import requests


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    client_id, client_secret, grant_code = sys.argv[1], sys.argv[2], sys.argv[3]
    dc = sys.argv[4] if len(sys.argv) > 4 else "com"

    resp = requests.post(
        f"https://accounts.zoho.{dc}/oauth/v2/token",
        params={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": grant_code,
        },
        timeout=30,
    )
    data = resp.json()
    if "refresh_token" not in data:
        print("Failed to obtain refresh token. Response:")
        print(data)
        print("\nCommon causes: grant code expired (regenerate it) or wrong data center.")
        return 1

    print("\n=== Paste these into your .env file ===\n")
    print(f"ZOHO_DC={dc}")
    print(f"ZOHO_CLIENT_ID={client_id}")
    print(f"ZOHO_CLIENT_SECRET={client_secret}")
    print(f"ZOHO_REFRESH_TOKEN={data['refresh_token']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
