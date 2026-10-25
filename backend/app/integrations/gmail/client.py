import base64
import re
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import getaddresses

import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import decrypt, encrypt
from app.integrations.gmail.normalize import TextHTML, normalize_reply
from app.models.entities import Integration
from app.repositories.tenant import TenantRepository

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def decode_body(payload):
    """Prefer plain text; safely extract text from HTML-only replies. Never read attachments."""
    if payload.get("filename") or payload.get("body", {}).get("attachmentId"):
        return ""
    parts = payload.get("parts", [])
    mime = payload.get("mimeType", "")
    if mime in {"text/plain", "text/html"}:
        encoded = payload.get("body", {}).get("data", "")
        text = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode(
            "utf-8", errors="replace"
        )[:24000]
        if mime == "text/html":
            parser = TextHTML()
            parser.feed(text)
            return "".join(parser.parts)[:12000]
        return text[:12000]
    plain = [part for part in parts if part.get("mimeType") == "text/plain"]
    chosen = plain if plain else parts
    return "\n".join(decode_body(part) for part in chosen)[:12000]


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class GmailClient:
    def __init__(self, db, agency_id):
        self.db = db
        self.integration = db.scalar(
            TenantRepository(db, agency_id)
            .query(Integration)
            .where(Integration.provider == "GMAIL")
        )
        if not self.integration or self.integration.status != "CONNECTED":
            raise AppError("INTEGRATION_NOT_CONNECTED", "Connect Gmail in settings", 409)

    def token(self):
        integration = self.integration
        if utc(integration.token_expires_at) <= datetime.now(UTC) + timedelta(seconds=60):
            cfg = settings()
            try:
                response = httpx.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": cfg.google_client_id,
                        "client_secret": cfg.google_client_secret,
                        "refresh_token": decrypt(integration.encrypted_refresh_token),
                        "grant_type": "refresh_token",
                    },
                    timeout=20,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise AppError(
                        "GMAIL_UNAVAILABLE", "Google token refresh is temporarily unavailable", 503
                    )
                if response.status_code != 200:
                    integration.status = "RECONNECT_REQUIRED"
                    self.db.commit()
                    raise AppError("GMAIL_RECONNECT_REQUIRED", "Reconnect Gmail to continue", 409)
                payload = response.json()
                integration.encrypted_access_token = encrypt(payload["access_token"])
                integration.token_expires_at = datetime.now(UTC) + timedelta(
                    seconds=payload["expires_in"]
                )
                self.db.commit()
            except httpx.HTTPError as exc:
                raise AppError(
                    "GMAIL_UNAVAILABLE", "Gmail token refresh is unavailable", 503
                ) from exc
        return decrypt(integration.encrypted_access_token)

    def request(self, method, path, **kwargs):
        try:
            response = httpx.request(
                method,
                f"{BASE}{path}",
                headers={"Authorization": f"Bearer {self.token()}"},
                timeout=30,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise AppError(
                "GMAIL_UNAVAILABLE", "Gmail request could not be confirmed", 503
            ) from exc
        if response.status_code == 403 and any(
            e.get("reason") in {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
            for e in response.json().get("error", {}).get("errors", [])
        ):
            raise AppError("GMAIL_UNAVAILABLE", "Gmail quota temporarily exhausted", 503)
        if response.status_code in {401, 403}:
            raise AppError(
                "GMAIL_PERMISSION_REQUIRED",
                "Reconnect Gmail and grant the required permissions",
                409,
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise AppError("GMAIL_UNAVAILABLE", "Gmail is temporarily unavailable", 503)
        if response.status_code >= 400:
            raise AppError("GMAIL_REQUEST_FAILED", "Gmail rejected the request", 422)
        return response.json()

    def context(self, invoice, brand, after=None):
        query = (
            f'{{from:{brand.contact_email} to:{brand.contact_email}}} "{invoice.invoice_number}"'
        )
        if after:
            query += f" after:{int(after.timestamp())}"
        threads, token = [], None
        while True:
            page = self.request(
                "GET",
                "/threads",
                params={"q": query, "maxResults": 50, **({"pageToken": token} if token else {})},
            )
            threads.extend(page.get("threads", []))
            token = page.get("nextPageToken")
            if not token:
                break
            if len(threads) >= 1000:
                raise AppError(
                    "GMAIL_CONTEXT_TOO_LARGE",
                    "Narrow the invoice mailbox context before syncing",
                    422,
                )
        result = []
        for thread in threads:
            messages = self.request(
                "GET", f"/threads/{thread['id']}", params={"format": "full"}
            ).get("messages", [])
            for message in messages:
                payload = message.get("payload", {})
                headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
                sender = (
                    getaddresses([headers.get("from", "")])[0][1] if headers.get("from") else ""
                )
                recipients = [email for _, email in getaddresses([headers.get("to", "")])]
                subject = headers.get("subject", "")[:250]
                body = normalize_reply(decode_body(payload))
                # Search may match quoted text. Independently require brand and invoice.
                if brand.contact_email.lower() not in {
                    sender.lower(),
                    *(r.lower() for r in recipients),
                }:
                    continue
                if not re.search(
                    r"(?<![\w-])" + re.escape(invoice.invoice_number) + r"(?![\w-])",
                    subject + "\n" + body,
                    re.I,
                ):
                    continue
                result.append(
                    {
                        "thread_id": thread["id"],
                        "message_id": message["id"],
                        "subject": subject,
                        "sender": sender,
                        "recipients": recipients,
                        "body": body,
                        "sent_at": datetime.fromtimestamp(
                            int(message.get("internalDate", "0")) / 1000, UTC
                        ),
                        "direction": "INBOUND"
                        if sender.lower() == brand.contact_email.lower()
                        else "OUTBOUND",
                    }
                )
        return sorted(result, key=lambda message: message["sent_at"])

    def find_sent(self, message_id):
        messages = self.request(
            "GET", "/messages", params={"q": f"in:sent rfc822msgid:{message_id}", "maxResults": 2}
        ).get("messages", [])
        return messages[0]["id"] if messages else None

    def send(self, recipient, subject, body, message_id):
        message = EmailMessage()
        message["To"] = recipient
        message["From"] = self.integration.external_account_id
        message["Subject"] = subject
        message["Message-ID"] = f"<{message_id}>"
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return self.request("POST", "/messages/send", json={"raw": raw})


class TestGmailClient:
    """Isolated test adapter, never selectable in production."""

    def __init__(self, db, agency_id):
        self.db, self.agency_id = db, agency_id

    def context(self, invoice, brand, after=None):
        return [
            {
                "thread_id": f"test-{invoice.id}",
                "message_id": f"context-{invoice.id}",
                "subject": f"Re: {invoice.invoice_number}",
                "sender": brand.contact_email,
                "recipients": ["finance@example.com"],
                "body": "We will process payment Friday.",
                "sent_at": datetime.now(UTC),
                "direction": "INBOUND",
            }
        ]

    def find_sent(self, message_id):
        return None

    def send(self, recipient, subject, body, message_id):
        return f"test-gmail-{message_id}"


def gmail_client(db, agency_id):
    return TestGmailClient(db, agency_id) if settings().test_mode else GmailClient(db, agency_id)
