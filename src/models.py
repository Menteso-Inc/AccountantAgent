"""Shared data structures passed between pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

InvoiceType = Literal["paid", "unpaid", "unspecified"]


@dataclass
class EmailMessage:
    """A single inbound email, normalized from the Gmail API."""

    message_id: str          # Gmail internal message id
    thread_id: str
    rfc822_message_id: str   # the "Message-ID" header, used for threading replies
    from_address: str
    from_name: str
    subject: str
    body_text: str
    to_addresses: list[str] = field(default_factory=list)   # for reply-all
    cc_addresses: list[str] = field(default_factory=list)


@dataclass
class Attendee:
    """A named person the request is for (e.g. an event delegate/ticket holder)."""

    name: str
    email: Optional[str] = None


@dataclass
class ParsedRequest:
    """What we extracted from the (possibly forwarded) request email."""

    pid: Optional[str]
    invoice_type: InvoiceType = "unspecified"
    confidence: float = 0.0
    source: str = "regex"          # "regex" | "llm" | "none"
    attendees: list[Attendee] = field(default_factory=list)
    discount_amount: float = 0.0   # e.g. "apply 100 USD discount" -> 100.0

    @property
    def is_actionable(self) -> bool:
        return bool(self.pid)


@dataclass
class LineItem:
    description: str
    quantity: float
    unit_price: float


@dataclass
class InvoiceDetails:
    """Invoice data pulled from Zoho + merged request extras, used to build Wave."""

    pid: str
    zoho_record_id: str
    customer_name: str
    customer_email: Optional[str]
    currency: str = "USD"
    status: str = ""                       # Zoho Payment_Status
    line_items: list[LineItem] = field(default_factory=list)
    memo: str = ""
    # routing: Zoho Events_or_Services -> companies.route()
    events_or_services: str = ""
    # merged from the parsed email (see pipeline):
    attendees: list[Attendee] = field(default_factory=list)
    discount_amount: float = 0.0
    is_paid: bool = False

    @property
    def total(self) -> float:
        return sum(li.quantity * li.unit_price for li in self.line_items)

    @property
    def net_total(self) -> float:
        return self.total - self.discount_amount


@dataclass
class GeneratedInvoice:
    wave_invoice_id: str
    invoice_number: str
    pdf_bytes: bytes
    view_url: str = ""
    status: str = ""


@dataclass
class ProcessResult:
    message_id: str
    ok: bool
    pid: Optional[str] = None
    company: Optional[str] = None
    zoho_record_id: Optional[str] = None
    wave_invoice_id: Optional[str] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None
