import logging
from datetime import date

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.xero.auth import get_valid_token

logger = logging.getLogger(__name__)

XERO_API_BASE = "https://api.xero.com/api.xro/2.0"


async def _headers() -> dict:
    token = await get_valid_token()
    return {
        "Authorization": f"Bearer {token['access_token']}",
        "xero-tenant-id": token["tenant_id"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def find_or_create_contact(name: str) -> str:
    headers = await _headers()
    async with httpx.AsyncClient() as client:
        # Search for existing contact
        resp = await client.get(
            f"{XERO_API_BASE}/Contacts",
            headers=headers,
            params={"where": f'Name=="{name}"'},
        )
        resp.raise_for_status()
        contacts = resp.json().get("Contacts", [])

        if contacts:
            return contacts[0]["ContactID"]

        # Create new contact
        resp = await client.post(
            f"{XERO_API_BASE}/Contacts",
            headers=headers,
            json={"Name": name},
        )
        resp.raise_for_status()
        new_contact = resp.json()["Contacts"][0]
        logger.info("Created Xero contact: %s", name)
        return new_contact["ContactID"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def create_bill(receipt_data: dict) -> str:
    contact_id = await find_or_create_contact(receipt_data["vendor_name"])
    account_code = settings.xero_default_account_code

    # Build line items
    line_items = []
    if receipt_data.get("line_items"):
        for item in receipt_data["line_items"]:
            line_items.append({
                "Description": item.get("description", receipt_data.get("description", "Receipt item")),
                "Quantity": item.get("quantity", 1),
                "UnitAmount": item.get("unit_amount", item.get("amount", 0)),
                "AccountCode": account_code,
            })
    else:
        line_items.append({
            "Description": receipt_data.get("description", "Receipt"),
            "Quantity": 1,
            "UnitAmount": receipt_data.get("amount", 0),
            "AccountCode": account_code,
        })

    invoice_date = receipt_data.get("date", date.today().isoformat())

    invoice_payload = {
        "Type": "ACCPAY",
        "Status": "DRAFT",
        "Contact": {"ContactID": contact_id},
        "Date": invoice_date,
        "DueDate": invoice_date,
        "LineAmountTypes": "Inclusive",
        "LineItems": line_items,
        "CurrencyCode": receipt_data.get("currency", "USD"),
    }

    if receipt_data.get("invoice_number"):
        invoice_payload["InvoiceNumber"] = receipt_data["invoice_number"]
    if receipt_data.get("description"):
        invoice_payload["Reference"] = receipt_data["description"][:255]

    headers = await _headers()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{XERO_API_BASE}/Invoices",
            headers=headers,
            json=invoice_payload,
        )
        resp.raise_for_status()
        invoice = resp.json()["Invoices"][0]

    invoice_id = invoice["InvoiceID"]
    logger.info(
        "Created Xero draft bill %s for %s (%.2f %s)",
        invoice_id,
        receipt_data["vendor_name"],
        receipt_data.get("amount", 0),
        receipt_data.get("currency", "USD"),
    )
    return invoice_id
