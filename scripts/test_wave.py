"""Test Wave invoice generation for one PID.

⚠️ This creates REAL records in your Wave business (Menteso, Inc.): a customer
(if new), the reusable "Professional Services (automated)" product (first run
only), and a SAVED invoice with the PID in its P.O. field. Re-running for the
same PID reuses the existing invoice (no duplicate).

  python scripts/test_wave.py                    # PID1615592
  python scripts/test_wave.py --pid PID1612240-US
  python scripts/test_wave.py --out C:/path/invoice.pdf
"""
import argparse
import sys

sys.path.insert(0, ".")
from src.config import get_config      # noqa: E402
from src.zoho_client import ZohoClient  # noqa: E402
from src.wave_client import WaveClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", default="PID1615592")
    ap.add_argument("--out", default=None, help="Where to save the generated PDF.")
    ap.add_argument("--email-to", default=None,
                    help="Comma-separated recipients to email the generated invoice to.")
    args = ap.parse_args()

    cfg = get_config()
    details = ZohoClient(cfg).find_by_pid(args.pid)
    if not details:
        print(f"No Zoho deal found for {args.pid}")
        return 1
    print(f"Zoho deal : {details.customer_name[:50]}")
    print(f"            {details.total:.2f} {details.currency} | status: {details.status}")

    invoice = WaveClient(cfg).generate(details)
    out = args.out or f"invoice-{args.pid}.pdf"
    with open(out, "wb") as f:
        f.write(invoice.pdf_bytes)

    print(f"\nWave invoice: #{invoice.invoice_number}  (id {invoice.wave_invoice_id})")
    print(f"Status      : {invoice.status}")
    print(f"PDF saved   : {out}  ({len(invoice.pdf_bytes)} bytes)")
    print(f"View in Wave: {invoice.view_url}")

    if args.email_to:
        from src.email_client import GmailClient
        recipients = [a.strip() for a in args.email_to.split(",") if a.strip()]
        body = (f"Hello,\n\nPlease find attached the invoice (#{invoice.invoice_number}) "
                f"for project {args.pid}.\n\nBest regards,\nMenteso Billing (automated)\n")
        sent_id = GmailClient(cfg).send_message(
            recipients, f"Invoice for project {args.pid}", body,
            pdf_bytes=invoice.pdf_bytes, pdf_filename=f"invoice-{args.pid}.pdf")
        print(f"Emailed to  : {', '.join(recipients)}  (message id {sent_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
