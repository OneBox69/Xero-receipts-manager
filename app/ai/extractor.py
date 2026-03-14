import json
import logging

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a receipt data extractor. Given an email's subject, sender, and body,
determine if it is a receipt, invoice, or payment confirmation, and extract structured data.

Respond with ONLY valid JSON (no markdown, no code fences) in this exact format:
{
    "is_receipt": true/false,
    "vendor_name": "Company Name",
    "amount": 99.99,
    "currency": "USD",
    "date": "2024-01-15",
    "description": "Brief description of what was purchased",
    "invoice_number": "INV-123 or null if not found",
    "line_items": [
        {
            "description": "Item description",
            "quantity": 1,
            "unit_amount": 49.99
        }
    ]
}

Rules:
- Set is_receipt to false for newsletters, marketing emails, shipping notifications without charges, etc.
- If it IS a receipt but you can't extract certain fields, use reasonable defaults (null for invoice_number, "USD" for currency).
- For amounts, extract the total/grand total, not subtotals.
- For dates, use ISO format (YYYY-MM-DD). If no date found, use null.
- line_items can be empty [] if individual items aren't listed — the total amount is more important.
- vendor_name should be the company name, not an email address."""


async def extract_receipt(subject: str, sender: str, body: str) -> dict | None:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    user_message = f"""Subject: {subject}
From: {sender}

Email Body:
{body[:8000]}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        result_text = response.content[0].text
        result = json.loads(result_text)

        if not result.get("is_receipt"):
            logger.info("Email not identified as receipt: %s", subject)
            return None

        logger.info(
            "Extracted receipt: %s - %.2f %s",
            result.get("vendor_name"),
            result.get("amount", 0),
            result.get("currency", "USD"),
        )
        return result

    except json.JSONDecodeError:
        logger.error("Failed to parse AI response as JSON: %s", response.content[0].text[:200])
        return None
    except Exception:
        logger.exception("AI extraction failed for email: %s", subject)
        raise
