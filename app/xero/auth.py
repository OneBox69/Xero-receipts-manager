import logging
import time
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.db.database import get_token, save_token

logger = logging.getLogger(__name__)

XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"

SCOPES = "openid accounting.transactions accounting.contacts offline_access"


def get_login_url() -> str:
    params = {
        "response_type": "code",
        "client_id": settings.xero_client_id,
        "redirect_uri": settings.xero_redirect_uri,
        "scope": SCOPES,
        "state": "xero-auth",
    }
    return f"{XERO_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.xero_redirect_uri,
            },
            auth=(settings.xero_client_id, settings.xero_client_secret),
        )
        resp.raise_for_status()
        token_data = resp.json()

    token_data["obtained_at"] = time.time()

    # Get tenant ID
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            XERO_CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        resp.raise_for_status()
        connections = resp.json()

    if connections:
        token_data["tenant_id"] = connections[0]["tenantId"]
        logger.info("Connected to Xero tenant: %s", connections[0].get("tenantName"))
    else:
        raise ValueError("No Xero tenants found for this account")

    save_token(settings.database_path, "xero", token_data)
    return token_data


async def get_valid_token() -> dict:
    token_data = get_token(settings.database_path, "xero")
    if not token_data:
        raise ValueError("Xero not authenticated. Visit /xero/login first.")

    # Refresh if expired (30 min access token, refresh 5 min early)
    expires_in = token_data.get("expires_in", 1800)
    obtained_at = token_data.get("obtained_at", 0)
    if time.time() > obtained_at + expires_in - 300:
        token_data = await _refresh_token(token_data)

    return token_data


async def _refresh_token(token_data: dict) -> dict:
    logger.info("Refreshing Xero access token")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token_data["refresh_token"],
            },
            auth=(settings.xero_client_id, settings.xero_client_secret),
        )
        resp.raise_for_status()
        new_token = resp.json()

    new_token["obtained_at"] = time.time()
    new_token["tenant_id"] = token_data["tenant_id"]
    save_token(settings.database_path, "xero", new_token)
    return new_token
