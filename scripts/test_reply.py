"""Test ONLY the reply path (no Wave needed).

Fetches a matching request email, builds a *placeholder* invoice PDF locally
(a real, valid PDF — not from Wave), and sends a threaded reply with it attached.
This proves the agent can send replies with attachments before Wave is wired in.

USAGE:
  # preview what it would send (no email sent):
  python scripts/test_reply.py
  # actually send the reply:
  python scripts/test_reply.py --send
  # target a specific email:
  python scripts/test_reply.py --query "is:unread from:sajan@menteso.com newer_than:2d" --send
"""
import argparse
import sys

sys.path.insert(0, ".")
from src.config import get_config          # noqa: E402
from src.email_client import GmailClient   # noqa: E402
from src.parser import parse_request       # noqa: E402
from src.zoho_client import ZohoClient     # noqa: E402


def _minimal_pdf(lines) -> bytes:
    """Build a valid one-page PDF containing the given text lines."""
    body_objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    ops = b"BT /F1 14 Tf 72 720 Td 18 TL "
    for i, line in enumerate(lines):
        esc = (line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
               .encode("latin-1", "replace"))
        ops += (b"(" + esc + b") Tj " if i == 0 else b"T* (" + esc + b") Tj ")
    ops += b"ET"
    body_objs.append(b"<< /Length " + str(len(ops)).encode() + b" >>\nstream\n"
                     + ops + b"\nendstream")
    body_objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(body_objs, start=1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_at = len(pdf)
    size = len(body_objs) + 1
    pdf += b"xref\n0 " + str(size).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += (b"trailer\n<< /Size " + str(size).encode() + b" /Root 1 0 R >>\n"
            b"startxref\n" + str(xref_at).encode() + b"\n%%EOF")
    return pdf


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="Actually send (default: preview).")
    ap.add_argument("--query", default="is:unread newer_than:2d")
    args = ap.parse_args()

    cfg = get_config()
    gmail = GmailClient(cfg)
    msgs = gmail.fetch_unprocessed(args.query)
    if not msgs:
        print(f"No emails match {args.query!r}. Send a test request first.")
        return 1

    msg = msgs[0]
    parsed = parse_request(msg.subject, msg.body_text)
    pid = parsed.pid or "UNKNOWN"

    # Best-effort Zoho lookup so the placeholder shows real data (optional).
    customer, amount, status = "(unknown customer)", 0.0, ""
    if parsed.pid:
        try:
            d = ZohoClient(cfg).find_by_pid(parsed.pid)
            if d:
                customer, amount, status = d.customer_name, d.total, d.status
        except Exception as e:  # noqa: BLE001
            print("(Zoho lookup skipped:", e, ")")

    pdf = _minimal_pdf([
        "PLACEHOLDER INVOICE (test)",
        "",
        f"Project ID: {pid}",
        f"Customer:   {customer}",
        f"Amount:     {amount:.2f} USD",
        f"Status:     {status}",
        "",
        "This is a test attachment. The real invoice will come from Wave.",
    ])
    body = (f"Hello,\n\nThis is an automated TEST reply for project {pid}. "
            f"A placeholder invoice is attached.\n\nMenteso Billing (automated)\n")

    print(f"Target email : {msg.subject!r} from {msg.from_address}")
    print(f"Reply to     : {msg.from_address}")
    print(f"PID / customer: {pid} / {customer} ({amount:.2f} USD)")
    print(f"PDF size     : {len(pdf)} bytes")

    if not args.send:
        print("\n(preview only - re-run with --send to actually send the reply)")
        return 0

    sent_id = gmail.send_reply(msg, pdf, body, pdf_filename=f"placeholder-{pid}.pdf")
    print(f"\n[SENT] Reply sent (message id {sent_id}) to {msg.from_address}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
