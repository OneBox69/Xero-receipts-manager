import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ai.extractor import extract_receipt
from app.config import settings
from app.db.database import (
    get_recent_emails,
    init_db,
    is_email_processed,
    record_email,
)
from app.gmail.client import get_new_emails
from app.xero import auth as xero_auth
from app.xero.client import create_bill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

RECEIPT_KEYWORDS = [
    "receipt", "invoice", "payment", "order", "charge", "transaction",
    "purchase", "billing", "subscription", "renewal", "paid", "confirmed",
    "total", "amount due", "payment received", "order confirmation",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.database_path)
    logger.info("App started. Database ready.")
    task = asyncio.create_task(_poll_gmail_loop())
    yield
    task.cancel()


async def _poll_gmail_loop():
    await asyncio.sleep(5)
    while True:
        try:
            await _poll_and_process()
        except Exception:
            logger.exception("Error during Gmail poll cycle")
        await asyncio.sleep(settings.gmail_poll_interval_seconds)


async def _poll_and_process():
    if not settings.gmail_app_password:
        return

    emails = get_new_emails()

    for email_data in emails:
        msg_id = email_data["message_id"]
        if is_email_processed(settings.database_path, msg_id):
            continue
        await _process_single_email(email_data)


async def _process_single_email(email_data: dict):
    msg_id = email_data["message_id"]
    subject = email_data["subject"]
    sender = email_data["sender"]
    body = email_data["body"]

    try:
        # Keyword pre-filter
        combined = f"{subject} {sender} {body}".lower()
        if not any(kw in combined for kw in RECEIPT_KEYWORDS):
            logger.info("Skipping non-receipt email: %s", subject)
            record_email(settings.database_path, msg_id, subject, sender, status="skipped")
            return

        # AI extraction
        receipt_data = await extract_receipt(subject=subject, sender=sender, body=body)

        if not receipt_data:
            record_email(settings.database_path, msg_id, subject, sender, status="not_receipt")
            return

        # Create Xero bill
        invoice_id = await create_bill(receipt_data)
        record_email(settings.database_path, msg_id, subject, sender, status="success", xero_invoice_id=invoice_id)
        logger.info("Processed receipt: %s → Xero bill %s", subject, invoice_id)

    except Exception as e:
        logger.exception("Failed to process email %s", msg_id)
        record_email(settings.database_path, msg_id, subject, sender, status="error", error_message=str(e)[:500])


app = FastAPI(title="Xero Receipts Manager", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "xero-receipts-manager"}


@app.get("/status")
async def status():
    emails = get_recent_emails(settings.database_path)
    return {"recent_emails": emails, "count": len(emails)}


# ── Xero OAuth ───────────────────────────────────────────────────────────────

@app.get("/xero/login")
async def xero_login():
    return RedirectResponse(xero_auth.get_login_url())


@app.get("/xero/callback")
async def xero_callback(code: str):
    try:
        await xero_auth.exchange_code(code)
        return HTMLResponse("<h2>Xero connected successfully!</h2><p>You can close this tab.</p>")
    except Exception as e:
        logger.exception("Xero OAuth callback failed")
        return HTMLResponse(f"<h2>Xero auth failed</h2><p>{e}</p>", status_code=500)
