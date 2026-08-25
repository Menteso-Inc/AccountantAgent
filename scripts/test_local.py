"""Run the agent locally — in stages, so you can test one integration at a time.

STAGE 1 — Gmail + parsing only (needs ONLY Google creds; Anthropic optional):
  python scripts/test_local.py --parse-only
  Reads unread emails and prints the PID/intent it extracts. Touches nothing else.

STAGE 2 — Full dry run (needs Google + Zoho; Wave/Anthropic NOT required):
  python scripts/test_local.py
  Fetches, parses, and looks up Zoho, then prints what it WOULD invoice. Creates
  no invoice and sends no email.

STAGE 3 — Live (needs Google + Zoho + Wave; Anthropic optional):
  python scripts/test_local.py --send
  Actually generates the Wave invoice and sends the reply.

Pick which emails to process (default: unread in the last 2 days):
  python scripts/test_local.py --query "from:you@menteso.com newer_than:7d"
"""
import argparse
import json
import logging
import sys

sys.path.insert(0, ".")
from src.config import get_config  # noqa: E402


def _parse_only(cfg, query: str) -> int:
    from src.email_client import GmailClient
    from src.parser import parse_request

    llm = None
    if cfg.anthropic_api_key:
        from src.llm import ClaudeParser
        llm = ClaudeParser(cfg)

    gmail = GmailClient(cfg)
    messages = gmail.fetch_unprocessed(query)
    print(f"\nFetched {len(messages)} email(s) for query: {query!r}\n")
    for m in messages:
        parsed = parse_request(m.subject, m.body_text, llm=llm)
        snippet = " ".join(m.body_text.split())[:140]
        print(f"- from: {m.from_address}")
        print(f"  subject: {m.subject!r}")
        print(f"  body: {snippet!r}")
        print(f"  -> PID={parsed.pid}  intent={parsed.invoice_type}  "
              f"source={parsed.source}  confidence={parsed.confidence}")
    if not messages:
        print("(no matching emails — send yourself a test email with a PID and retry)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse-only", action="store_true",
                    help="Stage 1: only read Gmail + extract PID. No Zoho/Wave.")
    ap.add_argument("--send", action="store_true",
                    help="Stage 3: actually create the invoice and send the reply.")
    ap.add_argument("--query", default="is:unread newer_than:2d",
                    help="Gmail search query for which emails to process.")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s %(message)s")

    cfg = get_config()

    if args.parse_only:
        return _parse_only(cfg, args.query)

    from src.pipeline import build_pipeline
    # Local runs use the in-memory store (DynamoDB is deploy-only); once an email
    # is replied to it's marked read, so it won't be picked up again.
    pipeline = build_pipeline(cfg, dry_run=not args.send, in_memory_store=True)
    results = pipeline.run(args.query)

    print("\n=== RESULTS ===")
    print(json.dumps([r.__dict__ for r in results], indent=2, default=str))
    if not args.send:
        print("\n(dry run — no invoice generated, no email sent. "
              "Re-run with --send to go live.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
