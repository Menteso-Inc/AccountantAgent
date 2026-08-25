"""AWS Lambda entry point.

Triggered on a schedule by EventBridge (see infra/template.yaml). Each invocation
polls the mailbox once and processes any unread invoice requests.

The same file runs locally:  python -m src.handler
"""
from __future__ import annotations

import json
import logging

from .config import get_config
from .pipeline import build_pipeline


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def lambda_handler(event, context):  # noqa: ANN001 - AWS signature
    config = get_config()
    _setup_logging(config.log_level)
    logging.getLogger(__name__).info("Invoice Request Agent invoked")

    pipeline = build_pipeline(config)
    results = pipeline.run()

    summary = {
        "processed": sum(1 for r in results if r.ok and not r.skipped_reason),
        "skipped": sum(1 for r in results if r.skipped_reason),
        "failed": sum(1 for r in results if not r.ok),
        "details": [
            {
                "message_id": r.message_id,
                "ok": r.ok,
                "pid": r.pid,
                "wave_invoice_id": r.wave_invoice_id,
                "error": r.error,
                "skipped_reason": r.skipped_reason,
            }
            for r in results
        ],
    }
    logging.getLogger(__name__).info("Run summary: %s", json.dumps(summary))
    return summary


if __name__ == "__main__":
    print(json.dumps(lambda_handler({}, None), indent=2))
