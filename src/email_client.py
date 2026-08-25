"""Gmail client — fetch unread invoice requests and reply with the PDF attached.

Auth uses an OAuth2 refresh token for the invoicerequest@ mailbox (minted once
by scripts/get_google_oauth_token.py), so no Workspace-admin setup is required.
"""
from __future__ import annotations

import base64
import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import getaddresses, parseaddr
from typing import Optional

from .config import Config
from .models import EmailMessage

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",  # read + send + mark-read
]


class GmailClient:
    def __init__(self, config: Config):
        from .config import require_config

        require_config(
            config, {"MAILBOX_ADDRESS": config.mailbox_address}, "section 1"
        )
        # Auth: prefer a service account (durable, no token expiry); otherwise
        # require the OAuth refresh-token trio.
        self._has_service_account = bool(
            config.google_service_account_json or config.google_service_account_file
        )
        if not self._has_service_account:
            require_config(
                config,
                {
                    "GOOGLE_CLIENT_ID": config.google_client_id,
                    "GOOGLE_CLIENT_SECRET": config.google_client_secret,
                    "GOOGLE_REFRESH_TOKEN": config.google_refresh_token,
                },
                "section 1",
            )
        self._cfg = config
        self._service = self._build_service()

    def _build_service(self):
        from googleapiclient.discovery import build

        creds = self._service_account_creds() if self._has_service_account \
            else self._oauth_creds()
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _service_account_creds(self):
        """Domain-wide-delegation creds that impersonate the mailbox. No refresh
        token, no expiry — the key mints access tokens directly on every call."""
        import json

        from google.oauth2 import service_account

        if self._cfg.google_service_account_json:
            info = json.loads(self._cfg.google_service_account_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=SCOPES
            )
        else:
            creds = service_account.Credentials.from_service_account_file(
                self._cfg.google_service_account_file, scopes=SCOPES
            )
        # impersonate the mailbox user (requires admin-granted delegation)
        return creds.with_subject(self._cfg.mailbox_address)

    def _oauth_creds(self):
        from google.oauth2.credentials import Credentials

        return Credentials(
            token=None,
            refresh_token=self._cfg.google_refresh_token,
            client_id=self._cfg.google_client_id,
            client_secret=self._cfg.google_client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )

    # --- fetch -----------------------------------------------------------
    def fetch_unprocessed(self, query: str = "is:unread newer_than:2d") -> list[EmailMessage]:
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", q=query)
            .execute()
        )
        out: list[EmailMessage] = []
        for ref in resp.get("messages", []):
            out.append(self._get_message(ref["id"]))
        return out

    def _get_message(self, message_id: str) -> EmailMessage:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        from_name, from_addr = parseaddr(headers.get("from", ""))
        to_list = [a for _, a in getaddresses([headers.get("to", "")]) if a]
        cc_list = [a for _, a in getaddresses([headers.get("cc", "")]) if a]
        return EmailMessage(
            message_id=message_id,
            thread_id=msg.get("threadId", ""),
            rfc822_message_id=headers.get("message-id", ""),
            from_address=from_addr,
            from_name=from_name or from_addr,
            subject=headers.get("subject", ""),
            body_text=self._extract_body(msg["payload"]),
            to_addresses=to_list,
            cc_addresses=cc_list,
        )

    def _extract_body(self, payload: dict) -> str:
        """Depth-first search for the first text/plain part (fallback: text/html)."""
        def walk(part) -> Optional[str]:
            mime = part.get("mimeType", "")
            body = part.get("body", {})
            if mime == "text/plain" and body.get("data"):
                return _b64url_decode(body["data"]).decode("utf-8", "replace")
            for sub in part.get("parts", []) or []:
                found = walk(sub)
                if found:
                    return found
            if mime == "text/html" and body.get("data"):
                return _b64url_decode(body["data"]).decode("utf-8", "replace")
            return None

        return walk(payload) or ""

    # --- reply -----------------------------------------------------------
    def send_reply(self, original: EmailMessage, pdf_bytes: bytes,
                   body_text: str, pdf_filename: str = "invoice.pdf") -> str:
        """Threaded reply to just the original sender."""
        return self._send_threaded(original, [original.from_address],
                                   pdf_bytes, body_text, pdf_filename)

    def reply_all(self, original: EmailMessage, pdf_bytes: bytes,
                  body_text: str, pdf_filename: str = "invoice.pdf") -> str:
        """Threaded reply to the sender + everyone on To/Cc (minus our own mailbox)."""
        me = self._cfg.mailbox_address.strip().lower()
        recipients: list[str] = []
        seen: set[str] = set()
        for addr in [original.from_address, *original.to_addresses, *original.cc_addresses]:
            a = (addr or "").strip()
            if not a or a.lower() == me or a.lower() in seen:
                continue
            seen.add(a.lower())
            recipients.append(a)
        return self._send_threaded(original, recipients or [original.from_address],
                                   pdf_bytes, body_text, pdf_filename)

    def _send_threaded(self, original: EmailMessage, recipients: list[str],
                       pdf_bytes: bytes, body_text: str, pdf_filename: str) -> str:
        mime = MIMEMultipart()
        mime["To"] = ", ".join(recipients)
        mime["From"] = self._cfg.mailbox_address
        subject = original.subject or "Your invoice"
        mime["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        if original.rfc822_message_id:
            mime["In-Reply-To"] = original.rfc822_message_id
            mime["References"] = original.rfc822_message_id

        mime.attach(MIMEText(body_text, "plain"))
        attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        mime.attach(attachment)

        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        sent = (
            self._service.users()
            .messages()
            .send(userId="me", body={"raw": raw, "threadId": original.thread_id})
            .execute()
        )
        return sent.get("id", "")

    def send_message(self, to, subject: str, body_text: str,
                     pdf_bytes: Optional[bytes] = None,
                     pdf_filename: str = "invoice.pdf") -> str:
        """Send a standalone email (optionally with a PDF) to one or more recipients."""
        mime = MIMEMultipart()
        mime["To"] = to if isinstance(to, str) else ", ".join(to)
        mime["From"] = self._cfg.mailbox_address
        mime["Subject"] = subject
        mime.attach(MIMEText(body_text, "plain"))
        if pdf_bytes:
            attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
            attachment.add_header("Content-Disposition", "attachment", filename=pdf_filename)
            mime.attach(attachment)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        sent = self._service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent.get("id", "")

    def mark_read(self, message_id: str) -> None:
        self._service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    # --- real-time push (Pub/Sub) ---------------------------------------
    def start_watch(self, topic_name: str, label_ids: Optional[list[str]] = None) -> dict:
        """Register/renew Gmail push notifications to a Pub/Sub topic.

        Returns {'historyId': ..., 'expiration': <ms epoch>}. The watch expires
        after ~7 days and must be renewed before then (see watch_handler.py).
        """
        body = {"topicName": topic_name, "labelIds": label_ids or ["INBOX"]}
        return self._service.users().watch(userId="me", body=body).execute()

    def stop_watch(self) -> dict:
        """Turn off push notifications for the mailbox."""
        return self._service.users().stop(userId="me").execute()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
