import logging

from app.gmail.client import get_gmail_service
from app.config import settings
from app.db.database import set_state

logger = logging.getLogger(__name__)


def setup_gmail_watch() -> dict:
    """Set up Gmail push notifications via Pub/Sub. Must be renewed every 7 days."""
    service = get_gmail_service()

    request_body = {
        "topicName": settings.gmail_pubsub_topic,
        "labelIds": ["INBOX"],
    }

    result = service.users().watch(userId="me", body=request_body).execute()

    history_id = result.get("historyId")
    if history_id:
        set_state(settings.database_path, "last_history_id", str(history_id))

    logger.info(
        "Gmail watch set up. Expiration: %s, historyId: %s",
        result.get("expiration"),
        history_id,
    )
    return result


def stop_gmail_watch() -> None:
    """Stop Gmail push notifications."""
    service = get_gmail_service()
    service.users().stop(userId="me").execute()
    logger.info("Gmail watch stopped")
