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
from app.gmail import client as gmail_client
from app.gmail.parser import get_email_content, get_new_message_ids
from app.xero import auth as xero_auth
from app.xero.client import create_bill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.database_path)
    logger.info("App started. Database ready.")

    # Start Gmail polling loop
    task = asyncio.create_task(_poll_gmail_loop())
    yield
    task.cancel()


async def _poll_gmail_loop():
    """Periodically poll Gmail for new emails and process receipts."""
    # Wait a bit on startup to let things settle
    await asyncio.sleep(5)

    while True:
        try:
            await _poll_and_process()
        except Exception:
            logger.exception("Error during Gmail poll cycle")

        await asyncio.sleep(settings.gmail_poll_interval_seconds)


async def _poll_and_process():
    """Single poll cycle: fetch new messages and process them."""
    try:
        message_ids = get_new_message_ids()
    except ValueError as e:
        logger.warning("Gmail not ready: %s", e)
        return

    for msg_id in message_ids:
        if is_email_processed(settings.database_path, msg_id):
            continue
        await _process_single_email(msg_id)


async def _process_single_email(message_id: str):
    """Process a single email: fetch → filter → AI extract → create Xero bill."""
    try:
        email = get_email_content(message_id)
        if not email:
            record_email(
                settings.database_path,
                message_id,
                subject="(filtered out)",
                sender="",
                status="skipped",
            )
            return

        # AI extraction
        receipt_data = await extract_receipt(
            subject=email["subject"],
            sender=email["sender"],
            body=email["body"],
        )

        if not receipt_data:
            record_email(
                settings.database_path,
                message_id,
                subject=email["subject"],
                sender=email["sender"],
                status="not_receipt",
            )
            return

        # Create Xero bill
        invoice_id = await create_bill(receipt_data)

        record_email(
            settings.database_path,
            message_id,
            subject=email["subject"],
            sender=email["sender"],
            status="success",
            xero_invoice_id=invoice_id,
        )
        logger.info("Processed receipt: %s → Xero bill %s", email["subject"], invoice_id)

    except Exception as e:
        logger.exception("Failed to process email %s", message_id)
        record_email(
            settings.database_path,
            message_id,
            subject="(error)",
            sender="",
            status="error",
            error_message=str(e)[:500],
        )


app = FastAPI(title="Xero Receipts Manager", lifespan=lifespan)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "xero-receipts-manager"}


# ── Status ───────────────────────────────────────────────────────────────────

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


# ── Gmail OAuth ──────────────────────────────────────────────────────────────

@app.get("/gmail/login")
async def gmail_login():
    return RedirectResponse(gmail_client.get_login_url())


@app.get("/gmail/callback")
async def gmail_callback(code: str):
    try:
        await gmail_client.exchange_code(code)
        return HTMLResponse("<h2>Gmail connected successfully!</h2><p>You can close this tab.</p>")
    except Exception as e:
        logger.exception("Gmail OAuth callback failed")
        return HTMLResponse(f"<h2>Gmail auth failed</h2><p>{e}</p>", status_code=500)
