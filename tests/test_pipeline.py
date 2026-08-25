"""Pipeline tests with fully mocked clients — run offline, no credentials.

    pytest tests/test_pipeline.py -v
"""
import sys

sys.path.insert(0, ".")
from src.idempotency import InMemoryStore  # noqa: E402
from src.models import EmailMessage, GeneratedInvoice, InvoiceDetails, LineItem  # noqa: E402
from src.pipeline import Pipeline  # noqa: E402


class FakeGmail:
    def __init__(self, messages):
        self._messages = messages
        self.sent = []
        self.marked_read = []

    def fetch_unprocessed(self, query="is:unread newer_than:2d"):
        return self._messages

    def send_reply(self, original, pdf_bytes, body_text, pdf_filename="invoice.pdf"):
        self.sent.append((original.message_id, pdf_filename, pdf_bytes))
        return "sent-1"

    def reply_all(self, original, pdf_bytes, body_text, pdf_filename="invoice.pdf"):
        self.sent.append((original.message_id, pdf_filename, pdf_bytes))
        return "sent-all-1"

    def mark_read(self, message_id):
        self.marked_read.append(message_id)


class FakeZoho:
    def __init__(self, mapping):
        self._mapping = mapping

    def find_by_pid(self, pid):
        return self._mapping.get(pid)


class FakeWave:
    def __init__(self):
        self.calls = []

    def generate(self, details, company):
        self.calls.append((details.pid, company.key))
        return GeneratedInvoice(
            wave_invoice_id="wave-1", invoice_number="INV-1",
            pdf_bytes=b"%PDF-1.4 fake", status="SAVED",
        )


def _msg(mid="m1", subject="Invoice", body="Please invoice PID: 500", frm="a@b.com"):
    return EmailMessage(
        message_id=mid, thread_id="t1", rfc822_message_id="<x@mail>",
        from_address=frm, from_name="A", subject=subject, body_text=body,
    )


def _details(pid="500", events="Menteso Services"):
    d = InvoiceDetails(pid=pid, zoho_record_id="z1", customer_name="Acme",
                       customer_email="acme@x.com", currency="USD",
                       events_or_services=events)
    d.line_items.append(LineItem("Services", 1, 1000.0))
    return d


def _pipeline(gmail, zoho, wave, dry_run=False):
    return Pipeline(config=None, gmail=gmail, zoho=zoho, wave=wave,
                    store=InMemoryStore(), llm=None, dry_run=dry_run)


def test_happy_path_generates_and_replies():
    gmail = FakeGmail([_msg()])
    p = _pipeline(gmail, FakeZoho({"500": _details()}), FakeWave())
    results = p.run()
    assert results[0].ok is True
    assert results[0].wave_invoice_id == "wave-1"
    assert gmail.sent and gmail.sent[0][1] == "invoice-500.pdf"
    assert gmail.marked_read == ["m1"]


def test_no_pid_is_recorded_as_failure():
    gmail = FakeGmail([_msg(body="just saying hi")])
    p = _pipeline(gmail, FakeZoho({}), FakeWave())
    results = p.run()
    assert results[0].ok is False
    assert results[0].skipped_reason == "no_pid_found"
    assert not gmail.sent


def test_unrouted_company_is_skipped():
    gmail = FakeGmail([_msg(body="Invoice PID: 500")])
    p = _pipeline(gmail, FakeZoho({"500": _details(events="Some Random Event")}), FakeWave())
    results = p.run()
    assert results[0].ok is False
    assert results[0].skipped_reason == "unrouted_company"
    assert not gmail.sent


def test_routes_to_company_and_replies():
    gmail = FakeGmail([_msg(body="Invoice PID: 500")])
    wave = FakeWave()
    p = _pipeline(gmail, FakeZoho({"500": _details(events="WLF 2026 Europe")}), wave)
    results = p.run()
    assert results[0].ok is True
    assert results[0].company == "WLF"
    assert wave.calls == [("500", "WLF")]
    assert gmail.sent  # reply-all sent


def test_pid_not_in_zoho_is_handled():
    gmail = FakeGmail([_msg(body="Invoice PID: 999")])
    p = _pipeline(gmail, FakeZoho({"500": _details()}), FakeWave())
    results = p.run()
    assert results[0].ok is False
    assert results[0].skipped_reason == "pid_not_in_zoho"
    assert not gmail.sent


def test_dry_run_does_not_send():
    gmail = FakeGmail([_msg()])
    p = _pipeline(gmail, FakeZoho({"500": _details()}), FakeWave(), dry_run=True)
    results = p.run()
    assert results[0].ok is True
    assert results[0].skipped_reason == "dry_run"
    assert not gmail.sent


def test_claim_is_exclusive_then_blocks():
    from src.models import ProcessResult
    s = InMemoryStore()
    assert s.claim("m1") is True       # first worker wins the claim
    assert s.claim("m1") is False      # second concurrent worker is blocked
    s.record(ProcessResult("m1", ok=True))
    assert s.claim("m1") is False      # completed -> never reprocessed


def test_failed_message_is_reclaimable():
    from src.models import ProcessResult
    s = InMemoryStore()
    assert s.claim("m2") is True
    s.record(ProcessResult("m2", ok=False, error="transient boom"))
    assert s.claim("m2") is True       # transient failure -> retryable


def test_terminal_skip_not_reclaimable():
    from src.models import ProcessResult
    s = InMemoryStore()
    s.claim("m3")
    s.record(ProcessResult("m3", ok=False, skipped_reason="pid_not_in_zoho"))
    assert s.claim("m3") is False      # decided skip -> not retried


def test_idempotency_skips_second_time():
    gmail = FakeGmail([_msg()])
    p = _pipeline(gmail, FakeZoho({"500": _details()}), FakeWave())
    p.run()
    # process the same message again through the same store
    second = p.process_one(_msg())
    assert second.skipped_reason == "already_processed"
