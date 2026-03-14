# Xero Receipts Manager

## What This Project Does
Polls a Gmail inbox for receipt/payment emails, uses Claude AI to extract structured receipt data, and creates draft Bills (Accounts Payable) in Xero.

## Architecture
```
Gmail (polled every 60s) → Keyword filter → Claude AI extract → Xero draft bill
```
All state stored in SQLite (`data/app.db`).

## Tech Stack
- **Python 3.12**, **FastAPI**, **uvicorn**
- **google-api-python-client** for Gmail API
- **httpx** for Xero API (raw REST)
- **anthropic** SDK for Claude AI extraction
- **SQLite** for dedup, tokens, app state
- **tenacity** for retries on Xero API calls

## Project Structure
- `app/main.py` — FastAPI app, all routes, Gmail polling loop, email processing
- `app/config.py` — Pydantic settings from `.env`
- `app/db/database.py` — SQLite init, CRUD helpers
- `app/gmail/client.py` — Gmail OAuth flow, service builder
- `app/gmail/parser.py` — Email fetching via history API, keyword filter, MIME parsing
- `app/ai/extractor.py` — Claude Sonnet receipt extraction (email → structured JSON)
- `app/xero/auth.py` — Xero OAuth 2.0 flow, token refresh
- `app/xero/client.py` — Create contacts, create draft ACCPAY invoices

## Key Design Decisions
- **Polling** instead of Pub/Sub — simpler, no Google Cloud setup needed
- Bills created as **DRAFT** — user reviews in Xero before approving
- **Keyword pre-filter** runs before AI to save Claude API costs
- **Dedup** via `gmail_message_id` in `processed_emails` table
- Xero tokens auto-refresh (access=30min, refresh=60day)

## Running Locally
```bash
cp .env.example .env   # fill in credentials
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Deployment (Zeabur)
- Uses `Dockerfile`; mount persistent volume at `/app/data/` for SQLite
- After deploy: visit `/xero/login` then `/gmail/login` to authorize
- Polling starts automatically after Gmail is authorized

## Routes
- `GET /health` — healthcheck
- `GET /status` — last 20 processed emails
- `GET /xero/login` → `/xero/callback` — Xero OAuth
- `GET /gmail/login` → `/gmail/callback` — Gmail OAuth
