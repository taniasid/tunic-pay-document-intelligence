"""
LLM extraction layer:

Sends document image(s) to Claude via the Anthropic API and returns a
validated ExtractedFields object. Handles:
  - Multi-page PDFs (pages summarised in a single prompt)
  - Retry on malformed JSON (up to MAX_RETRIES times)
  - Partial-result fallback so scoring can still run
  - temperature=0 + JSON-only system prompt for consistency
"""

from __future__ import annotations
import json
import time
import requests
from typing import Optional

from pydantic import ValidationError

from .models import ExtractedFields
from .ingest import FilePayload, CONFIDENCE_THRESHOLD

# claude-opus-4-5 via OpenRouter — strong vision + reliable JSON instruction-following.
MODEL = "anthropic/claude-opus-4-5"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_RETRIES = 2

SYSTEM_PROMPT = """You are a document analysis AI for a payment fraud investigation platform.

Analyse the provided document image(s) and return ONLY a single valid JSON object — no markdown fences, no explanation, no preamble.

The JSON must conform to this exact schema (use null for any field that is not present or not applicable):

{
  "entity_name": string | null,
  "amount": number | null,
  "currency": string | null,
  "date": string | null,
  "counterparty": string | null,
  "platform": string | null,
  "contact_details": string | null,
  "red_flags": [string],
  "urgency_language_detected": boolean,
  "category": one of ["invoice","marketplace_listing_screenshot","chat_screenshot","website_screenshot","other"],
  "category_confidence": number between 0.0 and 1.0
}

Field guidance:
- entity_name: the primary named party (seller, issuer, sender)
- amount: the single most significant monetary figure as a plain number
- currency: ISO 4217 code (USD, EUR, GBP) or crypto token symbol
- date: ISO 8601 (YYYY-MM-DD); use the most relevant date shown
- counterparty: the other named party (buyer, recipient, employer)
- platform: app, marketplace, or exchange name visible in the document
- contact_details: phone number, email, username, or wallet address
- red_flags: list each suspicious element as a short phrase
- urgency_language_detected: true if pressure, urgency, or "act now" language appears
- category_confidence: your confidence (0–1) in the category assignment

If multiple pages are provided, synthesise across all pages before answering.
Return ONLY the JSON object."""


def extract(payload: FilePayload, api_key: str) -> tuple[ExtractedFields, list[str]]:
    """
    Call the LLM via OpenRouter and return (ExtractedFields, warnings).

    warnings is a list of strings describing any problems encountered.
    On total failure a default ExtractedFields(category='other') is returned
    so the scoring layer can still produce a partial result.
    """
    warnings: list[str] = []
    raw_json: Optional[str] = None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/tunic-pay",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            start = time.time()
            body = {
                "model": MODEL,
                "max_tokens": 1024,
                "temperature": 0,   # Maximise consistency across repeated runs
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    _build_user_message(payload),
                ],
            }
            response = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=60)
            response.raise_for_status()
            latency_ms = int((time.time() - start) * 1000)
            raw_json = response.json()["choices"][0]["message"]["content"].strip()

            # Strip accidental markdown fences
            if raw_json.startswith("```"):
                raw_json = raw_json.split("```")[1]
                if raw_json.startswith("json"):
                    raw_json = raw_json[4:]
                raw_json = raw_json.strip()

            parsed = json.loads(raw_json)
            fields = ExtractedFields(**parsed)

            # Confidence-gated routing: low-confidence → force 'other'
            if fields.category_confidence < CONFIDENCE_THRESHOLD:
                warnings.append(
                    f"Category confidence {fields.category_confidence:.2f} below "
                    f"threshold {CONFIDENCE_THRESHOLD} — routed to 'other' for review."
                )
                fields.category = "other"

            return fields, warnings

        except json.JSONDecodeError as exc:
            warnings.append(f"Attempt {attempt}: JSON parse error — {exc}")
        except ValidationError as exc:
            warnings.append(f"Attempt {attempt}: Schema validation failed — {exc}")
        except requests.HTTPError as exc:
            warnings.append(f"Attempt {attempt}: HTTP error — {exc.response.status_code}: {exc.response.text[:200]}")
            break   # No point retrying a hard HTTP error

    # All retries exhausted — return safe default
    warnings.append("All extraction attempts failed; returning default fields.")
    return ExtractedFields(category="other", category_confidence=0.0), warnings


def _build_user_message(payload: FilePayload) -> dict:
    """Build the OpenAI-compatible message with one image block per page."""
    content = []

    if len(payload.images_b64) > 1:
        content.append({
            "type": "text",
            "text": f"This document has {len(payload.images_b64)} pages. Analyse all pages together."
        })

    for i, b64 in enumerate(payload.images_b64):
        mime = payload.mime_type if i == 0 else "image/png"
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{b64}"
            }
        })

    content.append({"type": "text", "text": "Analyse this document and return the JSON."})
    return {"role": "user", "content": content}