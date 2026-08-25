"""Claude-based extraction fallback.

Only invoked when the regex parser can't find a PID. Uses Anthropic tool-use so
the model is forced to return a structured result instead of prose.
"""
from __future__ import annotations

import logging
from typing import Optional

from .config import Config
from .models import ParsedRequest

logger = logging.getLogger(__name__)

_EXTRACT_TOOL = {
    "name": "record_invoice_request",
    "description": "Record the structured details extracted from an invoice-request email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pid": {
                "type": ["string", "null"],
                "description": "The Project ID (PID) mentioned in the email, or null if none is present.",
            },
            "invoice_type": {
                "type": "string",
                "enum": ["paid", "unpaid", "unspecified"],
                "description": "Whether the sender is asking for a paid invoice, an unpaid invoice, or did not specify.",
            },
            "confidence": {
                "type": "number",
                "description": "0.0-1.0 confidence that the extracted PID is correct.",
            },
        },
        "required": ["pid", "invoice_type", "confidence"],
    },
}

_SYSTEM = (
    "You extract structured fields from invoice-request emails. "
    "A PID is a Project ID: a short alphanumeric code. "
    "If no PID is clearly present, return pid=null. Do not invent one."
)


class ClaudeParser:
    """Callable wrapper: instance(subject, body) -> ParsedRequest | None."""

    def __init__(self, config: Config):
        # Imported lazily so unit tests that never touch Claude don't need the SDK.
        import anthropic

        self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._model = config.anthropic_model

    def __call__(self, subject: str, body_text: str) -> Optional[ParsedRequest]:
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=300,
                system=_SYSTEM,
                tools=[_EXTRACT_TOOL],
                tool_choice={"type": "tool", "name": "record_invoice_request"},
                messages=[
                    {
                        "role": "user",
                        "content": f"Subject: {subject}\n\nBody:\n{body_text}",
                    }
                ],
            )
        except Exception:  # network / API errors shouldn't crash the pipeline
            logger.exception("Claude extraction call failed")
            return None

        for block in resp.content:
            if block.type == "tool_use" and block.name == "record_invoice_request":
                data = block.input
                pid = data.get("pid")
                return ParsedRequest(
                    pid=pid,
                    invoice_type=data.get("invoice_type", "unspecified"),
                    confidence=float(data.get("confidence", 0.0)),
                    source="llm",
                )
        return None
