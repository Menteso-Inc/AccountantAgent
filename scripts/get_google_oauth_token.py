"""One-time helper: mint a Gmail refresh token for invoicerequest@menteso.com.

WHAT YOU NEED FIRST (docs/SETUP.md section 1):
  * A Google Cloud project with the Gmail API enabled.
  * An OAuth 2.0 Client ID of type "Desktop app". Download its JSON as
    client_secret.json into this folder.

RUN:
  pip install google-auth-oauthlib
  python scripts/get_google_oauth_token.py

A browser opens; sign in AS invoicerequest@menteso.com and approve. The script
prints GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN — paste
those three into your .env file.
"""
import json
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CLIENT_SECRET_FILE = os.path.join(os.path.dirname(__file__), "client_secret.json")


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency. Run:  pip install google-auth-oauthlib")
        return 1

    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"Place your OAuth client JSON at: {CLIENT_SECRET_FILE}")
        print("(Google Cloud Console -> APIs & Services -> Credentials -> "
              "Create OAuth client ID -> Desktop app -> Download JSON)")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    # access_type=offline + prompt=consent guarantees a refresh_token is returned.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    with open(CLIENT_SECRET_FILE) as f:
        installed = json.load(f)["installed"]

    print("\n=== Paste these into your .env file ===\n")
    print(f"GOOGLE_CLIENT_ID={installed['client_id']}")
    print(f"GOOGLE_CLIENT_SECRET={installed['client_secret']}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("\n(Keep these secret — do not commit them.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
