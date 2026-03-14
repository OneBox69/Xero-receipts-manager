import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.ai.extractor import extract_receipt
from app.config import settings
from app.db.database import (
    get_recent_emails,
    init_db,
    is_email_processed,
    record_email,
)
from app.gmail import client as gmail_client
from app.gmail.parser import decode_pubsub_notification, get_email_content, get_new_message_ids
from app.gmail.watcher import setup_gmail_watch
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

    # Try to renew Gmail watch on startup
    try:
        setup_gmail_watch()
        logger.info("Gmail watch renewed on startup")
    except Exception as e:
        logger.warning("Could not set up Gmail watch on startup: %s", e)

    # Schedule daily watch renewal
    task = asyncio.create_task(_daily_watch_renewal())
    yield
    task.cancel()


async def _daily_watch_renewal():
    while True:
        await asyncio.sleep(86400)  # 24 hours
        try:
            setup_gmail_watch()
            logger.info("Gmail watch renewed (daily)")
        except Exception as e:
            logger.error("Daily Gmail watch renewal failed: %s", e)


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
    url = xero_auth.get_login_url()
    return RedirectResponse(url)


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
    url = gmail_client.get_login_url()
    return RedirectResponse(url)


@app.get("/gmail/callback")
async def gmail_callback(code: str):
    try:
        await gmail_client.exchange_code(code)
        # Set up watch after auth
        try:
            setup_gmail_watch()
        except Exception as e:
            logger.warning("Gmail watch setup after auth failed: %s", e)
        return HTMLResponse("<h2>Gmail connected successfully!</h2><p>You can close this tab.</p>")
    except Exception as e:
        logger.exception("Gmail OAuth callback failed")
        return HTMLResponse(f"<h2>Gmail auth failed</h2><p>{e}</p>", status_code=500)


# ── Gmail Webhook (Pub/Sub push) ─────────────────────────────────────────────

@app.post("/webhook/gmail")
async def gmail_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle Gmail Pub/Sub push notification. Returns 200 immediately."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "invalid"}, status_code=400)

    background_tasks.add_task(_process_notification, body)
    return JSONResponse({"status": "ok"})


async def _process_notification(notification: dict):
    """Background task: process Gmail push notification."""
    try:
        pubsub_data = decode_pubsub_notification(notification)
        if not pubsub_data:
            logger.warning("Empty Pub/Sub notification")
            return

        history_id = str(pubsub_data.get("historyId", ""))
        if not history_id:
            return

        message_ids = get_new_message_ids(history_id)

        for msg_id in message_ids:
            if is_email_processed(settings.database_path, msg_id):
                logger.info("Skipping already processed email: %s", msg_id)
                continue

            await _process_single_email(msg_id)

    except Exception:
        logger.exception("Failed to process Gmail notification")


async def _process_single_email(message_id: str):
    """Process a single email: fetch → filter → AI extract → create Xero bill."""
    try:
        email = get_email_content(message_id)
        if not email:
            # Not a receipt or no body — record as skipped
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
        logger.info("Successfully processed receipt email: %s → Xero bill %s", email["subject"], invoice_id)

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
