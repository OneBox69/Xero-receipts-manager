# Xero Receipts Manager

## What This Project Does
Watches a Gmail inbox for receipt/payment emails via Google Pub/Sub push notifications, uses Claude AI to extract structured receipt data, and creates draft Bills (Accounts Payable) in Xero.

## Architecture
```
Gmail → Pub/Sub push → FastAPI /webhook/gmail → Fetch email → Keyword filter → Claude AI extract → Xero draft bill
```
All state stored in SQLite (`data/app.db`).

## Tech Stack
- **Python 3.12**, **FastAPI**, **uvicorn**
- **google-api-python-client** for Gmail API
- **httpx** for Xero API (raw REST, not xero-python SDK for requests)
- **anthropic** SDK for Claude AI extraction
- **SQLite** for dedup, tokens, app state
- **tenacity** for retries on Xero API calls

## Project Structure
- `app/main.py` — FastAPI app, all routes, webhook handler, background processing
- `app/config.py` — Pydantic settings from `.env`
- `app/db/database.py` — SQLite init, CRUD helpers
- `app/gmail/client.py` — Gmail OAuth flow, service builder
- `app/gmail/parser.py` — Pub/Sub decoding, email fetching, keyword filter, MIME parsing
- `app/gmail/watcher.py` — Gmail `users.watch()` setup/renewal
- `app/ai/extractor.py` — Claude Sonnet receipt extraction (email → structured JSON)
- `app/xero/auth.py` — Xero OAuth 2.0 flow, token refresh
- `app/xero/client.py` — Create contacts, create draft ACCPAY invoices

## Key Design Decisions
- Bills are created as **DRAFT** — user reviews in Xero before approving
- **Keyword pre-filter** runs before AI to save Claude API costs
- Pub/Sub delivers at-least-once — **dedup** via `gmail_message_id` in `processed_emails` table
- Xero tokens auto-refresh (access=30min, refresh=60day)
- Gmail watch auto-renews daily (expires after 7 days)

## Running Locally
```bash
cp .env.example .env   # fill in credentials
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Deployment (Zeabur)
- Uses `Dockerfile`; mount persistent volume at `/app/data/` for SQLite
- After deploy: visit `/xero/login` then `/gmail/login` to authorize
- Google Cloud Pub/Sub push subscription must point to `https://<url>/webhook/gmail`

## Routes
- `GET /health` — healthcheck
- `GET /status` — last 20 processed emails
- `GET /xero/login` → `/xero/callback` — Xero OAuth
- `GET /gmail/login` → `/gmail/callback` — Gmail OAuth
- `POST /webhook/gmail` — Pub/Sub push endpoint (returns 200 immediately, processes in background)
