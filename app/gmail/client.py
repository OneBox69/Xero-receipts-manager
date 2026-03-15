import email
import imaplib
import logging
from email.header import decode_header

from app.config import settings
from app.db.database import get_state, set_state

logger = logging.getLogger(__name__)


def _connect() -> imaplib.IMAP4_SSL:
    """Connect to Gmail via IMAP."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(settings.gmail_user_email, settings.gmail_app_password)
    return mail


def get_new_emails() -> list[dict]:
    """Fetch unprocessed emails from Gmail inbox."""
    mail = _connect()
    mail.select("INBOX")

    # Get the last seen UID
    last_uid = get_state(settings.database_path, "last_email_uid")

    if last_uid:
        # Search for emails newer than last seen UID
        status, data = mail.uid("search", None, f"UID {int(last_uid) + 1}:*")
    else:
        # First run: get last 10 emails
        status, data = mail.search(None, "ALL")
        if status == "OK" and data[0]:
            all_ids = data[0].split()
            recent_ids = all_ids[-10:]  # Last 10
            data = [b" ".join(recent_ids)]

    if status != "OK" or not data[0]:
        mail.logout()
        return []

    email_ids = data[0].split()
    emails = []

    for eid in email_ids:
        try:
            if last_uid:
                status, msg_data = mail.uid("fetch", eid, "(RFC822)")
                uid = eid.decode()
            else:
                status, msg_data = mail.fetch(eid, "(RFC822 UID)")
                # Extract UID from response
                uid_line = msg_data[0][0].decode() if msg_data[0][0] else ""
                uid = _extract_uid(uid_line) or eid.decode()

            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = _decode_header(msg.get("Subject", ""))
            sender = _decode_header(msg.get("From", ""))
            body = _get_body(msg)

            emails.append({
                "message_id": uid,
                "subject": subject,
                "sender": sender,
                "body": body,
            })
        except Exception:
            logger.exception("Failed to fetch email %s", eid)

    # Update last seen UID
    if emails:
        # Get the highest UID
        mail.select("INBOX")
        status, data = mail.uid("search", None, "ALL")
        if status == "OK" and data[0]:
            highest_uid = data[0].split()[-1].decode()
            set_state(settings.database_path, "last_email_uid", highest_uid)

    mail.logout()
    logger.info("Fetched %d new emails", len(emails))
    return emails


def _extract_uid(response_line: str) -> str | None:
    """Extract UID from IMAP fetch response."""
    import re
    match = re.search(r"UID (\d+)", response_line)
    return match.group(1) if match else None


def _decode_header(value: str) -> str:
    """Decode email header value."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _get_body(msg: email.message.Message) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # Fallback to HTML
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    return _strip_html(html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                return _strip_html(text)
            return text
    return ""


def _strip_html(html: str) -> str:
    """Basic HTML tag stripping."""
    import re
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
