"""Unit tests for the regex parser — run offline, no credentials needed.

    pip install pytest
    pytest tests/test_parser.py -v
"""
import sys

sys.path.insert(0, ".")
from src.parser import parse_request  # noqa: E402


def test_extracts_pid_with_colon():
    r = parse_request("Invoice request", "Please send the invoice for PID: 10432")
    assert r.pid == "10432"
    assert r.source == "regex"


def test_extracts_pid_with_hash():
    r = parse_request("PID#ABC-99 invoice", "")
    assert r.pid == "ABC-99"


def test_extracts_project_id_phrase():
    r = parse_request("Hi", "Could you invoice Project ID 7781 please")
    assert r.pid == "7781"


def test_extracts_canonical_pid_token():
    # Real menteso PIDs look like "PID1615592" (value already starts with PID).
    r = parse_request("Invoice request", "Please raise the invoice for PID1615592, thanks")
    assert r.pid == "PID1615592"


def test_canonical_pid_normalized_uppercase():
    r = parse_request("hi", "invoice for pid1615592 please")
    assert r.pid == "PID1615592"


def test_labelled_canonical_pid():
    r = parse_request("hi", "Project ID: PID1615592")
    assert r.pid == "PID1615592"


def test_detects_unpaid_intent():
    r = parse_request("Invoice", "Need the UNPAID invoice for PID 55")
    assert r.pid == "55"
    assert r.invoice_type == "unpaid"


def test_detects_paid_intent():
    r = parse_request("Invoice", "Send the paid invoice for pid 55")
    assert r.invoice_type == "paid"


def test_not_paid_reads_as_unpaid():
    r = parse_request("Invoice", "This one is not paid yet, PID 55")
    assert r.invoice_type == "unpaid"


def test_no_pid_and_no_llm_returns_none():
    r = parse_request("Hello", "Just checking in, no project mentioned", llm=None)
    assert r.pid is None
    assert r.is_actionable is False


def test_extracts_attendees_and_discount():
    body = ("Please make the paid invoice for:\n"
            "1. Atty. Nino Don L. Lina (ninodonlina@gmail.com)\n"
            "2. Cynia Basilisa R. Joseph (cyniaj2020@gmail.com)\n"
            "PID: PID1615602\nPlease apply 100 USD as a discount code.")
    r = parse_request("Paid Invoice - PID1615602", body)
    assert r.pid == "PID1615602"
    assert r.invoice_type == "paid"
    assert r.discount_amount == 100.0
    assert len(r.attendees) == 2
    assert r.attendees[0].email == "ninodonlina@gmail.com"


def test_signature_email_is_not_an_attendee():
    r = parse_request("hi", "invoice for PID1615592\nRegards\nEmail anchal@menteso.com")
    assert r.attendees == []


def test_llm_fallback_used_when_regex_fails():
    from src.models import ParsedRequest

    def fake_llm(subject, body):
        return ParsedRequest(pid="LLM-123", invoice_type="unpaid",
                             confidence=0.8, source="llm")

    r = parse_request("Hello", "the widget rollout job from last month", llm=fake_llm)
    assert r.pid == "LLM-123"
    assert r.source == "llm"
