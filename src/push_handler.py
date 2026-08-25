"""AWS Lambda entry point for the real-time Gmail push trigger.

Wired to API Gateway (HTTP API) POST /gmail/push. Google Cloud Pub/Sub delivers
a push notification here whenever the mailbox changes. We verify the request is
genuinely from Google, then run the same pipeline as the scheduled poller. The
notification body only carries {emailAddress, historyId}; the actual unread
messages are fetched by the pipeline, and DynamoDB idempotency prevents any email
from being processed twice (across both push and the safety-net poll).
"""
from __future__ import annotations

import base64
import json
import logging

from .config import get_config
from .oidc import verify_push_request
from .pipeline import build_pipeline


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def _header(headers: dict, name: str):
    if not headers:
        return None
    lname = name.lower()
    for key, value in headers.items():
        if key.lower() == lname:
            return value
    return None


def _decode_body(event: dict) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", "replace")
    return body


def lambda_handler(event, context):  # noqa: ANN001 - AWS signature
    config = get_config()
    _setup_logging(config.log_level)
    log = logging.getLogger(__name__)

    # 1. authenticate the caller
    auth = _header(event.get("headers") or {}, "authorization")
    if not verify_push_request(auth, config.push_audience, config.push_sa_email):
        log.warning("Rejected push request: OIDC verification failed")
        return {"statusCode": 403, "body": "forbidden"}

    # 2. log what changed (best-effort; not required to process)
    try:
        envelope = json.loads(_decode_body(event) or "{}")
        data = envelope.get("message", {}).get("data")
        if data:
            notif = json.loads(base64.b64decode(data).decode("utf-8", "replace"))
            log.info(
                "Gmail push: address=%s historyId=%s",
                notif.get("emailAddress"), notif.get("historyId"),
            )
    except Exception:  # malformed envelope shouldn't stop processing
        log.exception("Could not parse Pub/Sub envelope (continuing)")

    # 3. process any unread invoice requests
    try:
        results = build_pipeline(config).run()
    except Exception:
        log.exception("Pipeline run failed")
        # Non-2xx -> Pub/Sub retries with backoff (at-least-once delivery).
        return {"statusCode": 500, "body": "error"}

    processed = sum(1 for r in results if r.ok and not r.skipped_reason)
    log.info("Push run complete: processed=%d of %d candidate(s)", processed, len(results))
    return {"statusCode": 200, "body": "ok"}
