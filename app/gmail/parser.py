import base64
import logging
import re

from app.gmail.client import get_gmail_service
from app.db.database import get_state, set_state
from app.config import settings

logger = logging.getLogger(__name__)

RECEIPT_KEYWORDS = [
    "receipt", "invoice", "payment", "order", "charge", "transaction",
    "purchase", "billing", "subscription", "renewal", "paid", "confirmed",
    "total", "amount due", "payment received", "order confirmation",
]


def get_new_message_ids() -> list[str]:
    """Poll Gmail for new messages since last check using history API."""
    service = get_gmail_service()
    stored_history = get_state(settings.database_path, "last_history_id")

    if not stored_history:
        # First run: get current historyId and recent messages
        profile = service.users().getProfile(userId="me").execute()
        history_id = str(profile["historyId"])
        set_state(settings.database_path, "last_history_id", history_id)

        # Fetch last 10 messages to process on first run
        results = service.users().messages().list(
            userId="me", maxResults=10, labelIds=["INBOX"]
        ).execute()
        return [m["id"] for m in results.get("messages", [])]

    try:
        results = service.users().history().list(
            userId="me",
            startHistoryId=stored_history,
            historyTypes=["messageAdded"],
        ).execute()
    except Exception as e:
        if "404" in str(e) or "historyId" in str(e).lower():
            logger.warning("History ID expired, resetting")
            profile = service.users().getProfile(userId="me").execute()
            set_state(settings.database_path, "last_history_id", str(profile["historyId"]))
            return []
        raise

    # Update stored history ID
    new_history_id = results.get("historyId", stored_history)
    set_state(settings.database_path, "last_history_id", new_history_id)

    message_ids = []
    for record in results.get("history", []):
        for msg in record.get("messagesAdded", []):
            msg_id = msg["message"]["id"]
            labels = msg["message"].get("labelIds", [])
            if "DRAFT" not in labels and "SENT" not in labels:
                message_ids.append(msg_id)

    logger.info("Found %d new messages since history %s", len(message_ids), stored_history)
    return message_ids


def get_email_content(message_id: str) -> dict | None:
    """Fetch and parse a Gmail message, returning subject, sender, and body."""
    service = get_gmail_service()
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    subject = headers.get("subject", "(no subject)")
    sender = headers.get("from", "unknown")

    body = _extract_body(msg["payload"])

    if not body:
        logger.debug("No text body found for message %s", message_id)
        return None

    # Keyword pre-filter
    combined = f"{subject} {sender} {body}".lower()
    if not any(kw in combined for kw in RECEIPT_KEYWORDS):
        logger.info("Skipping non-receipt email: %s", subject)
        return None

    return {
        "message_id": message_id,
        "subject": subject,
        "sender": sender,
        "body": body,
    }


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from MIME parts."""
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    if mime_type.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _extract_body(part)
            if text:
                return text

    # Fallback: try HTML and strip tags
    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return _strip_html(html)

    # Check parts even for non-multipart
    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    return ""


def _strip_html(html: str) -> str:
    """Basic HTML tag stripping."""
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
