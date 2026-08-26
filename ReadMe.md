# Invoice Request Agent

> 📖 **Full documentation: [AGENT.md](AGENT.md)** — what it does, the end-to-end
> flow, the business rules, architecture, and everything to understand. Credential
> setup is in [docs/SETUP.md](docs/SETUP.md).

An autonomous service that turns invoice-request emails into sent invoices — no
human in the loop.

When an email arrives at **`invoicerequest@menteso.com`**, the agent:

1. **Reads** the email and extracts the **PID (Project ID)** + paid/unpaid intent
   (regex first, Claude fallback for messy phrasing).
2. **Looks up** the matching record in **Zoho CRM** (Opportunities/Deals) by the
   PID custom field and reads the invoice details.
3. **Generates** the invoice in **Wave**.
4. **Replies** to the original sender with the invoice **PDF attached**.

It runs on **AWS Lambda**, triggered in **real time** by Gmail push notifications
(Google Cloud Pub/Sub → API Gateway → Lambda), with a low-frequency scheduled
poll as a safety net.

> **Note on "agents":** this is a *deployed backend service*, not a Claude Code
> subagent (`.claude/agents/*.md`). Those only run inside an interactive Claude
> Code session and can't run 24/7 on AWS. Claude is used here only as a library
> call inside the service, for resilient email parsing.

## Architecture

```
invoicerequest@menteso.com (Google Workspace)
        │  new mail → Gmail watch → Pub/Sub → API Gateway → push Lambda (real-time)
        │  (+ scheduled poll Lambda as a safety net; daily watch-renewer Lambda)
        ▼
  parse (regex → Claude)  →  Zoho CRM lookup by PID  →  Wave invoiceCreate + PDF
        │
        ▼
  reply to sender with PDF attached   +   DynamoDB audit / idempotency
```

## Repository layout

```
src/            application code:
                  config, parser, llm, zoho/wave/email clients, pipeline
                  handler.py       — scheduled poll (safety net)
                  push_handler.py  — real-time Gmail push (Pub/Sub → API Gateway)
                  watch_handler.py — daily Gmail watch renewal
                  oidc.py          — verifies push requests come from Google
scripts/        credential helpers, watch setup, local test runner
infra/          AWS SAM template (push Lambda + HTTP API, poll, renewer, DynamoDB, DLQ, alarm)
docs/SETUP.md   step-by-step credential setup — START HERE
tests/          offline unit tests (parser, pipeline, oidc)
.env.example    every value you must provide, labeled FILL_ME
```

## Quickstart

```bash
# 1. install deps
pip install -r requirements.txt

# 2. run the offline tests (no credentials needed)
pip install pytest && pytest -v

# 3. gather credentials — follow docs/SETUP.md, then:
cp .env.example .env      # and fill in the FILL_ME values

# 4. dry run against your real inbox (fetches + parses + looks up Zoho,
#    but does NOT create invoices or send email)
python scripts/test_local.py

# 5. go live locally (creates the Wave invoice and sends the reply)
python scripts/test_local.py --send

# 6. deploy to AWS (see docs/SETUP.md section 5)
cd infra && sam build && sam deploy --guided
```

## What you need to provide

Everything is listed in [`docs/SETUP.md`](docs/SETUP.md) and mirrored as
`FILL_ME` placeholders in [`.env.example`](.env.example):

- **Google**: OAuth client + a refresh token for the mailbox
- **Zoho CRM**: client id/secret + refresh token, and the module/field API names
- **Wave**: full-access API token + business & income-account IDs *(paid Wave plan required)*
- **Anthropic**: an API key
- **AWS**: an account to deploy the SAM stack

## Status / next steps

The full scaffold, all integrations, real-time push, tests, and infra are in
place. Before going live you must: (a) supply credentials per `docs/SETUP.md`,
(b) confirm your Zoho module/field names with `scripts/inspect_zoho_module.py`,
(c) verify the Wave invoice fields against your live business with
`scripts/wave_bootstrap.py`, and (d) complete the Pub/Sub setup in
`docs/SETUP.md` section 6 to enable real-time delivery.
