"""DynamoDB-backed processed-message tracking.

Guarantees each inbound email is handled/replied-to **exactly once**, even when
two workers run at the same time (e.g. the push Lambda and the safety-net poll).
Also doubles as an audit trail (pid, zoho id, wave invoice id, status, error).

Concurrency model: `claim()` performs an atomic conditional write to reserve a
message before any work happens. Only one worker can win the claim; the other
skips. A message becomes claimable again only if a prior attempt hit a transient
error, or an in-flight claim went stale (a crashed worker).

For local dry-runs where AWS isn't configured, use `InMemoryStore`.
"""
from __future__ import annotations

import logging
import time
from typing import Protocol

from .config import Config
from .models import ProcessResult

logger = logging.getLogger(__name__)

# An in-flight claim older than this (seconds) is assumed crashed and reclaimable.
STALE_CLAIM_SECONDS = 900


def _terminal_state(result: ProcessResult) -> str:
    """'done' = never retry (success, or a decided skip like no-PID / not-in-Zoho).
    'failed' = a transient error; allow a later run to retry it."""
    if result.ok or result.skipped_reason:
        return "done"
    return "failed"


class ProcessedStore(Protocol):
    def claim(self, message_id: str) -> bool: ...
    def record(self, result: ProcessResult) -> None: ...


class DynamoProcessedStore:
    def __init__(self, config: Config):
        import boto3

        self._table = boto3.resource(
            "dynamodb", region_name=config.aws_region
        ).Table(config.ddb_table_name)

    def claim(self, message_id: str) -> bool:
        """Atomically reserve a message. True if this worker should process it."""
        from botocore.exceptions import ClientError

        now = int(time.time())
        try:
            self._table.put_item(
                Item={
                    "message_id": message_id,
                    "claim_state": "processing",
                    "processed_at": now,
                },
                # Win the claim only if: no record yet, OR the last attempt failed
                # (retryable), OR a previous claim is stale (crashed mid-flight).
                ConditionExpression=(
                    "attribute_not_exists(message_id) "
                    "OR #st = :failed "
                    "OR (#st = :processing AND #pa < :stale)"
                ),
                ExpressionAttributeNames={"#st": "claim_state", "#pa": "processed_at"},
                ExpressionAttributeValues={
                    ":failed": "failed",
                    ":processing": "processing",
                    ":stale": now - STALE_CLAIM_SECONDS,
                },
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False  # another worker holds it, or it's already done
            raise

    def record(self, result: ProcessResult) -> None:
        self._table.put_item(
            Item={
                "message_id": result.message_id,
                "claim_state": _terminal_state(result),
                "ok": result.ok,
                "pid": result.pid,
                "zoho_record_id": result.zoho_record_id,
                "wave_invoice_id": result.wave_invoice_id,
                "error": result.error,
                "skipped_reason": result.skipped_reason,
                "processed_at": int(time.time()),
            }
        )


class InMemoryStore:
    """Non-persistent store for local testing / --dry-run (single-threaded)."""

    def __init__(self) -> None:
        self._seen: dict[str, ProcessResult] = {}
        self._claimed: set[str] = set()

    def claim(self, message_id: str) -> bool:
        prior = self._seen.get(message_id)
        if prior is not None and _terminal_state(prior) == "done":
            return False  # already completed
        if message_id in self._claimed and prior is None:
            return False  # currently in-flight
        self._claimed.add(message_id)
        return True

    def record(self, result: ProcessResult) -> None:
        self._seen[result.message_id] = result


def build_store(config: Config, in_memory: bool = False) -> ProcessedStore:
    return InMemoryStore() if in_memory else DynamoProcessedStore(config)
