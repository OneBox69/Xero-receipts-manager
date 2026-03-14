import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_connection(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str) -> None:
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS processed_emails (
            gmail_message_id TEXT PRIMARY KEY,
            subject TEXT,
            sender TEXT,
            processed_at TEXT NOT NULL,
            xero_invoice_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS oauth_tokens (
            service TEXT PRIMARY KEY,
            token_data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", db_path)


def is_email_processed(db_path: str, message_id: str) -> bool:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT 1 FROM processed_emails WHERE gmail_message_id = ?", (message_id,)
    ).fetchone()
    conn.close()
    return row is not None


def record_email(
    db_path: str,
    message_id: str,
    subject: str,
    sender: str,
    status: str,
    xero_invoice_id: str | None = None,
    error_message: str | None = None,
) -> None:
    conn = get_connection(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO processed_emails
           (gmail_message_id, subject, sender, processed_at, xero_invoice_id, status, error_message)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            message_id,
            subject,
            sender,
            datetime.now(timezone.utc).isoformat(),
            xero_invoice_id,
            status,
            error_message,
        ),
    )
    conn.commit()
    conn.close()


def get_recent_emails(db_path: str, limit: int = 20) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM processed_emails ORDER BY processed_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_token(db_path: str, service: str, token_data: dict) -> None:
    conn = get_connection(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO oauth_tokens (service, token_data, updated_at)
           VALUES (?, ?, ?)""",
        (service, json.dumps(token_data), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_token(db_path: str, service: str) -> dict | None:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT token_data FROM oauth_tokens WHERE service = ?", (service,)
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["token_data"])
    return None


def set_state(db_path: str, key: str, value: str) -> None:
    conn = get_connection(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    conn.close()


def get_state(db_path: str, key: str) -> str | None:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT value FROM app_state WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    if row:
        return row["value"]
    return None
