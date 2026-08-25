"""AWS Lambda entry point that (re)registers the Gmail push watch.

A Gmail watch expires after ~7 days, so EventBridge invokes this daily to renew
it (see infra/template.yaml). Renewing is idempotent — calling watch() again
simply extends the expiration.

Runs locally too:  python -m src.watch_handler
"""
from __future__ import annotations

import json
import logging

from .config import get_config
from .email_client import GmailClient


def lambda_handler(event, context):  # noqa: ANN001 - AWS signature
    config = get_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    log = logging.getLogger(__name__)

    if not config.pubsub_topic:
        raise RuntimeError(
            "PUBSUB_TOPIC is not set. Configure the real-time push trigger first "
            "(see docs/SETUP.md section 6)."
        )

    resp = GmailClient(config).start_watch(config.pubsub_topic)
    log.info("Gmail watch renewed: %s", json.dumps(resp))
    return {"historyId": resp.get("historyId"), "expiration": resp.get("expiration")}


if __name__ == "__main__":
    print(json.dumps(lambda_handler({}, None), indent=2))
