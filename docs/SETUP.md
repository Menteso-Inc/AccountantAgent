# Setup Guide — everything YOU need to provide

This is the checklist of credentials and IDs the agent needs. Each section tells
you where to get the value and which `.env` key to paste it into. Anything marked
`FILL_ME` in `.env.example` is filled in by following the matching section here.

> Copy `.env.example` to `.env` first: `cp .env.example .env`

At a glance, you will produce these values:

| Section | .env keys you fill in |
|---|---|
| 1. Google / Gmail | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` |
| 2. Zoho CRM | `ZOHO_DC`, `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_MODULE`, `ZOHO_PID_FIELD` |
| 3. Wave | `WAVE_API_TOKEN`, `WAVE_BUSINESS_ID`, `WAVE_INCOME_ACCOUNT_ID` |
| 4. Claude | `ANTHROPIC_API_KEY` |
| 5. AWS (deploy only) | populate the Secrets Manager secret |
| 6. Real-time push (optional) | `PUBSUB_TOPIC`, `PUSH_AUDIENCE`, `PUSH_SA_EMAIL` |

---

## 1. Google Workspace / Gmail

The agent reads from and replies as `invoicerequest@menteso.com`.

> **Prerequisite:** you must be able to sign in *as* `invoicerequest@menteso.com`
> during consent — the refresh token is minted for whoever approves, and the agent
> reads/sends as that account (`userId="me"`). If `invoicerequest@` is only an
> alias or a group (no separate login), use a service account with domain-wide
> delegation instead of this OAuth flow.

1. Go to <https://console.cloud.google.com> (sign in with a menteso.com account)
   → **project dropdown → New Project** (e.g. `menteso-invoice-agent`) → select it.
2. **APIs & Services → Library →** search **Gmail API** → **Enable**.
3. **APIs & Services → OAuth consent screen** (newer console: **Google Auth
   Platform**, <https://console.cloud.google.com/auth>) → **User type: `Internal`.**
   - Internal (Workspace-only) needs **no Google verification** for the Gmail
     scope, and its **refresh tokens do not expire every 7 days** — unlike an
     External app left in "Testing", which would break a 24/7 agent. Pick Internal.
   - Fill App name / support email / developer email → Save. (No need to add
     scopes here; the script requests the Gmail scope directly.)
4. **APIs & Services → Credentials → Create credentials → OAuth client ID →**
   Application type **Desktop app** (required — the script uses the loopback
   installed-app flow; not "Web"). Create → **Download JSON**.
5. Save that JSON as `scripts/client_secret.json`.
6. Run the token minter:
   ```bash
   pip install -r requirements.txt
   python scripts/get_google_oauth_token.py
   ```
   A browser opens — **sign in as `invoicerequest@menteso.com`** and approve.
7. The script prints `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `GOOGLE_REFRESH_TOKEN`. Paste all three into `.env`.

> The refresh token is long-lived (with Internal user type). If it ever stops
> working (password reset, revoked access), just re-run step 6.
>
> Troubleshooting: `redirect_uri_mismatch` → client isn't a Desktop app; recreate
> it. Refresh token prints as `None` → revoke the app at
> <https://myaccount.google.com/permissions> (as invoicerequest@) and rerun.
> `access_blocked`/"unverified" → switch the consent screen to Internal, or add
> invoicerequest@ under Test users.

### Option B (recommended for production): service account + domain-wide delegation

Durable auth — **no refresh token, never expires, no re-consent.** The agent
impersonates the mailbox using a private key. Requires Google Workspace **super
admin** access for the one-time authorization (step 4).

1. **Create the service account** (same `InvoiceReqAgent` project):
   <https://console.cloud.google.com/iam-admin/serviceaccounts?project=invoicereqagent>
   → **Create service account** → name `invoice-agent-gmail` → Create → skip the
   optional roles (Gmail delegation doesn't use GCP roles) → **Done**.
2. **Create a key:** click the service account → **Keys** tab → **Add key → Create
   new key → JSON** → download → save as `scripts/service_account.json`.
3. **Copy its Client ID:** on the service account details, copy the numeric
   **Unique ID / OAuth 2 Client ID** (e.g. `114857…`).
4. **Authorize it (super admin):** <https://admin.google.com> → **Security →
   Access and data control → API controls → Domain-wide delegation → Add new**:
   - **Client ID:** the numeric ID from step 3
   - **OAuth scopes:** `https://www.googleapis.com/auth/gmail.modify`
   - **Authorize**.
5. **Point the agent at the key:** in `.env` set
   `GOOGLE_SERVICE_ACCOUNT_FILE=scripts/service_account.json` and keep
   `MAILBOX_ADDRESS=invoicerequest@menteso.com` (the account it impersonates).
   Once set, this automatically replaces the OAuth token.
6. **Test:** `python scripts/test_local.py --parse-only` — now runs with no
   refresh token involved.

Notes: the mailbox must be a real Workspace **user** (not an alias/group) for
impersonation. `unauthorized_client` error → the delegation in step 4 isn't
authorized yet or the scope doesn't match exactly; propagation can take a few
minutes.

---

## 2. Zoho CRM

You need read access to the module that holds your Opportunities and the custom
Project ID field.

### 2a. Get a refresh token
1. Go to <https://api-console.zoho.com> → **Add Client → Self Client**.
2. Copy the **Client ID** and **Client Secret**.
3. On the **Generate Code** tab, enter scope:
   `ZohoCRM.modules.READ,ZohoCRM.settings.READ`, choose a duration, and generate
   a **grant code** (copy it quickly — it expires in minutes).
4. Exchange it for a refresh token (replace the placeholders; `dc` is your data
   center — `com`, `in`, `eu`, `com.au`, or `jp`):
   ```bash
   python scripts/get_zoho_refresh_token.py <client_id> <client_secret> <grant_code> com
   ```
5. Paste the printed `ZOHO_DC`, `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`,
   `ZOHO_REFRESH_TOKEN` into `.env`.

### 2b. Confirm the module + field API names
Display names ≠ API names ("Project ID" is likely `Project_ID`). List the real
ones:
```bash
python scripts/inspect_zoho_module.py            # lists modules
python scripts/inspect_zoho_module.py Deals      # lists fields in that module
```
- Set `ZOHO_MODULE` to the module whose label is *Opportunities* (usually `Deals`).
- Set `ZOHO_PID_FIELD` to the api_name of your Project ID field.
- If your invoice fields differ from the defaults, edit `FIELD_MAP` at the top of
  [`src/zoho_client.py`](../src/zoho_client.py) to match the api_names you saw.

---

## 3. Wave

> **⚠️ Wave's API requires a PAID plan (Pro or Advisor).** Free "Starter"
> accounts cannot authorize API access. Confirm your plan before spending time here.

1. Go to <https://developer.waveapps.com> and sign in with your Wave account.
2. Create a **full-access token** (Manage Applications / API tokens → Create token).
3. Paste it into `.env` as `WAVE_API_TOKEN`.
4. Discover your business and income-account IDs:
   ```bash
   python scripts/wave_bootstrap.py
   ```
5. Paste the printed `WAVE_BUSINESS_ID` and `WAVE_INCOME_ACCOUNT_ID` into `.env`.

> Wave's GraphQL schema is unversioned and can change. If `invoiceCreate` ever
> starts failing, re-run `wave_bootstrap.py` and check field names against
> <https://developer.waveapps.com>.

---

## 4. Claude (Anthropic)

Used only when the regex parser can't find a PID in a messy email.

1. Get an API key from <https://console.anthropic.com> → **API Keys**.
2. Paste it into `.env` as `ANTHROPIC_API_KEY`.
3. `ANTHROPIC_MODEL` is preset to a cheap, fast model — leave it unless you have a
   reason to change.

---

## 5. AWS (deployment only)

Local testing (sections 1–4) needs no AWS. To run the agent 24/7:

1. Install the AWS SAM CLI and configure AWS credentials (`aws configure`).
2. Build and deploy:
   ```bash
   cd infra
   sam build
   sam deploy --guided        # first time; accepts the defaults in samconfig.toml
   ```
3. This creates the Lambda, the every-2-minutes schedule, the DynamoDB table, a
   dead-letter queue, an error alarm, and an **empty Secrets Manager secret**
   named `invoice-request-agent/config`.
4. Put all your credentials into that secret as one JSON object (same keys as
   `.env`, minus the AWS-only ones):
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id invoice-request-agent/config \
     --secret-string file://secret.json
   ```
   where `secret.json` looks like:
   ```json
   {
     "MAILBOX_ADDRESS": "invoicerequest@menteso.com",
     "GOOGLE_CLIENT_ID": "...",
     "GOOGLE_CLIENT_SECRET": "...",
     "GOOGLE_REFRESH_TOKEN": "...",
     "ZOHO_DC": "com",
     "ZOHO_CLIENT_ID": "...",
     "ZOHO_CLIENT_SECRET": "...",
     "ZOHO_REFRESH_TOKEN": "...",
     "ZOHO_MODULE": "Deals",
     "ZOHO_PID_FIELD": "Project_ID",
     "WAVE_API_TOKEN": "...",
     "WAVE_BUSINESS_ID": "...",
     "WAVE_INCOME_ACCOUNT_ID": "...",
     "ANTHROPIC_API_KEY": "...",
     "ANTHROPIC_MODEL": "claude-haiku-4-5-20251001"
   }
   ```
   > Do NOT commit `secret.json`. Delete it after uploading.

The agent is now live. With push not yet configured it relies on the safety-net
poll (default every 30 min — lower it as noted above until push is set up). Watch
it in CloudWatch Logs (`/aws/lambda/invoice-request-agent-*`).

---

## 6. Real-time Gmail push (optional but recommended)

This replaces "poll every N minutes" with instant delivery: Gmail → Google Cloud
Pub/Sub → your AWS API Gateway → the push Lambda. The scheduled poll stays on as a
low-frequency safety net. **Do AWS (section 5) first** — you need the deployed push
endpoint URL before you can create the Pub/Sub subscription.

You'll need the `gcloud` CLI and the **same Google Cloud project** as section 1.

### 6a. Create the Pub/Sub topic and let Gmail publish to it
```bash
gcloud config set project <YOUR_GCP_PROJECT_ID>

gcloud pubsub topics create gmail-invoice-requests

# Allow Gmail's system account to publish change notifications to the topic:
gcloud pubsub topics add-iam-policy-binding gmail-invoice-requests \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```
Your topic is `projects/<YOUR_GCP_PROJECT_ID>/topics/gmail-invoice-requests`.

### 6b. Create a service account for Pub/Sub to authenticate to AWS
```bash
gcloud iam service-accounts create gmail-push-invoker \
  --display-name="Gmail push -> AWS invoker"
```
Its email is `gmail-push-invoker@<YOUR_GCP_PROJECT_ID>.iam.gserviceaccount.com`.

### 6c. Deploy AWS with the push values, then get the endpoint URL
Redeploy so the Lambda can verify Google's OIDC tokens:
```bash
cd infra
sam deploy --parameter-overrides \
  PubSubTopic="projects/<YOUR_GCP_PROJECT_ID>/topics/gmail-invoice-requests" \
  PushServiceAccountEmail="gmail-push-invoker@<YOUR_GCP_PROJECT_ID>.iam.gserviceaccount.com" \
  PushAudience="PLACEHOLDER"
```
Copy the `PushEndpointUrl` from the stack outputs, then redeploy once more with
`PushAudience` set to that exact URL (the audience must match what Pub/Sub sends):
```bash
sam deploy --parameter-overrides \
  PubSubTopic="projects/<YOUR_GCP_PROJECT_ID>/topics/gmail-invoice-requests" \
  PushServiceAccountEmail="gmail-push-invoker@<YOUR_GCP_PROJECT_ID>.iam.gserviceaccount.com" \
  PushAudience="<PushEndpointUrl from outputs>"
```

### 6d. Create the push subscription pointing at AWS
```bash
gcloud pubsub subscriptions create gmail-invoice-requests-push \
  --topic=gmail-invoice-requests \
  --push-endpoint="<PushEndpointUrl>" \
  --push-auth-service-account="gmail-push-invoker@<YOUR_GCP_PROJECT_ID>.iam.gserviceaccount.com" \
  --push-auth-token-audience="<PushEndpointUrl>" \
  --ack-deadline=60
```

### 6e. Register the Gmail watch
Put the topic in `.env` / the Secrets Manager JSON as `PUBSUB_TOPIC`, then start it:
```bash
python scripts/setup_gmail_watch.py       # local one-time registration
```
In AWS, the `invoice-request-agent-watch-renew` Lambda renews it daily
automatically (Gmail watches expire after ~7 days).

### 6f. Test it
Send an email to `invoicerequest@menteso.com` with a known test PID. Within a few
seconds you should see the `invoice-request-agent-push` Lambda fire in CloudWatch
Logs and a reply arrive with the PDF attached.

> **Security:** the push endpoint is public, so the Lambda verifies the Google-signed
> OIDC token on every request (audience + service-account email). If `PUSH_AUDIENCE`
> and `PUSH_SA_EMAIL` are both blank, verification is disabled — only leave them blank
> for local testing, never in production.
