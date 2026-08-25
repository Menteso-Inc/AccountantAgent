"""Register the Gmail push watch from your machine (one-time bring-up / testing).

Prereqs (docs/SETUP.md section 6):
  * A Pub/Sub topic exists and its publisher role is granted to
    gmail-api-push@system.gserviceaccount.com.
  * PUBSUB_TOPIC is set in .env  (projects/<gcp-project>/topics/<topic>).

RUN:
  python scripts/setup_gmail_watch.py            # register / renew the watch
  python scripts/setup_gmail_watch.py --stop     # turn push off
"""
import json
import sys

sys.path.insert(0, ".")
from src.config import get_config  # noqa: E402
from src.email_client import GmailClient  # noqa: E402


def main() -> int:
    cfg = get_config()
    client = GmailClient(cfg)

    if "--stop" in sys.argv:
        print("Stopping watch:", json.dumps(client.stop_watch()))
        return 0

    if not cfg.pubsub_topic:
        print("Set PUBSUB_TOPIC in .env first "
              "(e.g. projects/menteso-invoicing/topics/gmail-invoice-requests)")
        return 1

    resp = client.start_watch(cfg.pubsub_topic)
    print("Watch registered:", json.dumps(resp, indent=2))
    print(f"\nExpiration: {resp.get('expiration')} (ms epoch) — renew within 7 days. "
          f"In AWS the watch-renewer Lambda does this daily.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
