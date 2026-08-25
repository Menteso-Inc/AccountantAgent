"""Orchestrates the end-to-end flow for a batch of inbound emails.

For each unread email:
  1. skip if already processed (idempotency)
  2. parse  -> PID + intent (regex, Claude fallback)
  3. zoho   -> invoice details for that PID
  4. wave   -> generate invoice + PDF
  5. gmail  -> reply to sender with the PDF attached
  6. record the outcome (audit + idempotency)

Any failure on one email is caught, recorded, and does not stop the others.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from . import companies
from .config import Config
from .email_client import GmailClient
from .idempotency import ProcessedStore
from .models import EmailMessage, ProcessResult
from .parser import parse_request
from .wave_client import WaveClient
from .zoho_client import ZohoClient

logger = logging.getLogger(__name__)

REPLY_TEMPLATE = (
    "Hello,\n\n"
    "Please find attached invoice {number} for project {pid}.\n\n"
    "Best regards,\n"
    "{company} — automated billing\n"
)


class Pipeline:
    def __init__(
        self,
        config: Config,
        gmail: GmailClient,
        zoho: ZohoClient,
        wave: WaveClient,
        store: ProcessedStore,
        llm: Optional[Callable] = None,
        dry_run: bool = False,
    ):
        self._cfg = config
        self._gmail = gmail
        self._zoho = zoho
        self._wave = wave
        self._store = store
        self._llm = llm
        self._dry_run = dry_run

    def run(self, query: str = "is:unread newer_than:2d") -> list[ProcessResult]:
        messages = self._gmail.fetch_unprocessed(query)
        logger.info("Fetched %d candidate email(s)", len(messages))
        results = []
        for msg in messages:
            results.append(self.process_one(msg))
        return results

    def process_one(self, msg: EmailMessage) -> ProcessResult:
        # Atomically claim the message so concurrent workers can't double-send.
        if not self._store.claim(msg.message_id):
            logger.info("Skipping already-claimed/processed message %s", msg.message_id)
            return ProcessResult(msg.message_id, ok=True, skipped_reason="already_processed")

        parsed = None
        try:
            parsed = parse_request(msg.subject, msg.body_text, llm=self._llm)
            if not parsed.is_actionable:
                return self._skip(msg, None, "no_pid_found",
                                  "Could not extract a PID from the email")

            details = self._zoho.find_by_pid(parsed.pid)
            if details is None:
                return self._skip(msg, parsed.pid, "pid_not_in_zoho",
                                  f"No Zoho record for PID {parsed.pid}")

            # Route to the right company (Wave business) from the deal.
            company = companies.route(details.events_or_services)
            if company is None:
                return self._skip(msg, parsed.pid, "unrouted_company",
                                  f"Events_or_Services {details.events_or_services!r} "
                                  f"did not map to a known company")

            # Merge the parsed request extras into the invoice spec.
            details.attendees = parsed.attendees
            details.discount_amount = parsed.discount_amount
            details.is_paid = (parsed.invoice_type == "paid")

            if self._dry_run:
                logger.info(
                    "[dry-run] PID %s -> %s | customer=%s | total=%.2f %s | "
                    "discount=%.2f | attendees=%d | paid=%s | would reply-all",
                    parsed.pid, company.name, details.customer_name, details.net_total,
                    details.currency, details.discount_amount, len(details.attendees),
                    details.is_paid,
                )
                return ProcessResult(
                    msg.message_id, ok=True, pid=parsed.pid, company=company.key,
                    zoho_record_id=details.zoho_record_id, skipped_reason="dry_run",
                )

            invoice = self._wave.generate(details, company)
            body = REPLY_TEMPLATE.format(pid=parsed.pid, number=invoice.invoice_number,
                                         company=company.name)
            self._gmail.reply_all(
                msg, invoice.pdf_bytes, body, pdf_filename=f"invoice-{parsed.pid}.pdf",
            )
            self._gmail.mark_read(msg.message_id)

            result = ProcessResult(
                msg.message_id, ok=True, pid=parsed.pid, company=company.key,
                zoho_record_id=details.zoho_record_id,
                wave_invoice_id=invoice.wave_invoice_id,
            )
            self._store.record(result)
            logger.info("Processed %s -> %s invoice %s",
                        msg.message_id, company.key, invoice.invoice_number)
            return result

        except Exception as exc:  # noqa: BLE001 - isolate per-message failures
            logger.exception("Failed to process message %s", msg.message_id)
            result = ProcessResult(
                msg.message_id, ok=False, pid=getattr(parsed, "pid", None), error=str(exc),
            )
            self._store.record(result)
            return result

    def _skip(self, msg: EmailMessage, pid, reason: str, error: str) -> ProcessResult:
        result = ProcessResult(msg.message_id, ok=False, pid=pid,
                               skipped_reason=reason, error=error)
        self._store.record(result)
        return result


def build_pipeline(config: Config, dry_run: bool = False, in_memory_store: bool = False) -> Pipeline:
    """Wire together real clients from config. Used by handler.py and scripts."""
    from .idempotency import build_store
    from .llm import ClaudeParser

    gmail = GmailClient(config)
    zoho = ZohoClient(config)
    wave = WaveClient(config)
    store = build_store(config, in_memory=in_memory_store)
    if config.anthropic_api_key:
        llm = ClaudeParser(config)
    else:
        llm = None
        logger.warning(
            "No ANTHROPIC_API_KEY set — parsing runs regex-only (no Claude fallback)."
        )
    return Pipeline(config, gmail, zoho, wave, store, llm=llm, dry_run=dry_run)
