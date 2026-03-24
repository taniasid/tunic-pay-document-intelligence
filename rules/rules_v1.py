"""
Scoring rules v1.

Design principles:
  - Each rule is a plain function: (ExtractedFields) -> RuleResult
  - Rules are registered in RULES — adding a new rule = write a function + append it
  - Rules are independent of each other
  - All thresholds are module-level constants for easy tuning and audit

To add a new rule:
  1. Write a function matching the signature below
  2. Append it to RULES

Rule weights sum to > 1.0 intentionally; the scorer clamps the final
composite score to [0, 1]. This lets high-severity rules dominate without
requiring weights to be renormalised every time a new rule is added.
"""

from __future__ import annotations
from pipeline.models import ExtractedFields, RuleResult

RULE_SET_VERSION = "v1"

# ── Thresholds  ──────────────────────────────────

HIGH_AMOUNT_INVOICE = 10_000          # EUR/USD — flagged on invoices
HIGH_AMOUNT_MARKETPLACE = 5_000       # EUR/USD — flagged on marketplace listings
HIGH_AMOUNT_CHAT = 1_000              # Any promised payment in a chat is suspicious
CRYPTO_HIGH_VOLUME = 10_000           # USD volume threshold for crypto screenshots
MICRO_CAP_HOLDER_COUNT = 500          # Token with fewer holders than this is micro-cap
MIN_RED_FLAG_COUNT = 2                # Number of LLM red flags that triggers the rule
USDT_SALARY_KEYWORDS = ["usdt", "tether", "crypto", "bitcoin", "btc", "eth"]


# ── Individual rule functions ─────────────────────────────────────────────────

def rule_high_amount(fields: ExtractedFields) -> RuleResult:
    """
    R01 — Unusually high monetary amount for the document type.
    Large amounts increase fraud risk; thresholds are per-category.
    """
    triggered = False
    explanation = "Amount is within normal range for this document type."

    if fields.amount is None:
        return RuleResult(
            rule_id="R01_high_amount",
            triggered=False,
            weight=0.20,
            explanation="No amount found in document.",
        )

    if fields.category == "invoice" and fields.amount > HIGH_AMOUNT_INVOICE:
        triggered = True
        explanation = (
            f"Invoice amount {fields.amount} {fields.currency or ''} exceeds "
            f"threshold of {HIGH_AMOUNT_INVOICE}."
        )
    elif fields.category == "marketplace_listing_screenshot" and fields.amount > HIGH_AMOUNT_MARKETPLACE:
        triggered = True
        explanation = (
            f"Marketplace listing price {fields.amount} {fields.currency or ''} "
            f"exceeds threshold of {HIGH_AMOUNT_MARKETPLACE}."
        )
    elif fields.category == "chat_screenshot" and fields.amount > HIGH_AMOUNT_CHAT:
        triggered = True
        explanation = (
            f"Chat screenshot references payment of {fields.amount} "
            f"{fields.currency or ''} — high for an informal channel."
        )

    return RuleResult(rule_id="R01_high_amount", triggered=triggered, weight=0.20, explanation=explanation)


def rule_missing_invoice_date(fields: ExtractedFields) -> RuleResult:
    """
    R02 — Invoice missing a date or due date.
    Legitimate invoices always carry a date; absence suggests fabrication.
    """
    if fields.category != "invoice":
        return RuleResult(
            rule_id="R02_missing_invoice_date",
            triggered=False,
            weight=0.20,
            explanation="Rule only applies to invoices.",
        )
    triggered = fields.date is None
    explanation = (
        "Invoice has no date — a strong indicator of a fabricated document."
        if triggered
        else f"Invoice date present: {fields.date}."
    )
    return RuleResult(rule_id="R02_missing_invoice_date", triggered=triggered, weight=0.20, explanation=explanation)


def rule_urgency_language(fields: ExtractedFields) -> RuleResult:
    """
    R03 — Urgency or pressure language detected.
    Social-engineering fraud (pig butchering, advance-fee) relies on time pressure.
    """
    triggered = fields.urgency_language_detected
    explanation = (
        "Document contains urgency or pressure language — common in social-engineering fraud."
        if triggered
        else "No urgency language detected."
    )
    return RuleResult(rule_id="R03_urgency_language", triggered=triggered, weight=0.25, explanation=explanation)


def rule_llm_red_flags(fields: ExtractedFields) -> RuleResult:
    """
    R04 — LLM identified multiple independent red flags.
    Two or more distinct anomalies raise the overall risk profile.
    """
    count = len(fields.red_flags)
    triggered = count >= MIN_RED_FLAG_COUNT
    explanation = (
        f"LLM flagged {count} anomalies: {'; '.join(fields.red_flags[:5])}."
        if triggered
        else f"LLM flagged {count} anomaly — below threshold of {MIN_RED_FLAG_COUNT}."
    )
    return RuleResult(rule_id="R04_llm_red_flags", triggered=triggered, weight=0.20, explanation=explanation)


def rule_missing_counterparty(fields: ExtractedFields) -> RuleResult:
    """
    R05 — No counterparty identified on an invoice or marketplace listing.
    Genuine commercial documents always identify both parties.
    """
    applicable = fields.category in ("invoice", "marketplace_listing_screenshot")
    if not applicable:
        return RuleResult(
            rule_id="R05_missing_counterparty",
            triggered=False,
            weight=0.10,
            explanation="Rule only applies to invoices and marketplace listings.",
        )
    triggered = fields.counterparty is None
    explanation = (
        "No counterparty identified — legitimate commercial documents always name both parties."
        if triggered
        else f"Counterparty identified: {fields.counterparty}."
    )
    return RuleResult(rule_id="R05_missing_counterparty", triggered=triggered, weight=0.10, explanation=explanation)


def rule_crypto_payment_in_chat(fields: ExtractedFields) -> RuleResult:
    """
    R06 — Chat screenshot promises crypto / USDT salary or payment.
    Crypto-denominated wages in informal chat channels are a near-universal
    indicator of pig-butchering and task-scam fraud.
    """
    if fields.category != "chat_screenshot":
        return RuleResult(
            rule_id="R06_crypto_payment_in_chat",
            triggered=False,
            weight=0.30,
            explanation="Rule only applies to chat screenshots.",
        )

    # Check currency field and red_flags for crypto keywords
    searchable = " ".join([
        (fields.currency or "").lower(),
        " ".join(fields.red_flags).lower(),
        (fields.contact_details or "").lower(),
        (fields.entity_name or "").lower(),
    ])
    triggered = any(kw in searchable for kw in USDT_SALARY_KEYWORDS)
    explanation = (
        "Chat references crypto/USDT payment — strongly associated with task-scam fraud."
        if triggered
        else "No crypto payment terms detected in chat."
    )
    return RuleResult(rule_id="R06_crypto_payment_in_chat", triggered=triggered, weight=0.30, explanation=explanation)


def rule_micro_cap_token(fields: ExtractedFields) -> RuleResult:
    """
    R07 — Crypto exchange screenshot showing a token with very few holders.
    Micro-cap tokens with <500 holders are frequently used for wash-trading
    and layering in money-laundering schemes.
    """
    if fields.category != "website_screenshot":
        return RuleResult(
            rule_id="R07_micro_cap_token",
            triggered=False,
            weight=0.25,
            explanation="Rule only applies to website/exchange screenshots.",
        )

    # LLM should capture holder count in red_flags if it looks suspicious
    searchable = " ".join(fields.red_flags).lower()
    triggered = (
        "holder" in searchable
        or "micro" in searchable
        or "low liquidity" in searchable
        or "wash" in searchable
        or (fields.platform and "dex" in fields.platform.lower())
    )
    explanation = (
        "Screenshot shows DEX trading with very low holder count — "
        "indicative of micro-cap token manipulation or wash-trading."
        if triggered
        else "No micro-cap or low-liquidity signals detected."
    )
    return RuleResult(rule_id="R07_micro_cap_token", triggered=triggered, weight=0.25, explanation=explanation)


def rule_implausible_listing_data(fields: ExtractedFields) -> RuleResult:
    """
    R08 — Marketplace listing contains implausible or contradictory data.
    Examples: negative engine size, mismatched vehicle specs, impossible dates.
    Fabricated listings often contain subtle data errors introduced when
    copy-pasting from templates.
    """
    if fields.category != "marketplace_listing_screenshot":
        return RuleResult(
            rule_id="R08_implausible_listing_data",
            triggered=False,
            weight=0.20,
            explanation="Rule only applies to marketplace listings.",
        )
    searchable = " ".join(fields.red_flags).lower()
    triggered = (
        "implausible" in searchable
        or "inconsistent" in searchable
        or "incorrect" in searchable
        or "negative" in searchable
        or "mismatch" in searchable
        or "suspicious" in searchable
    )
    explanation = (
        f"Listing data appears implausible or contradictory: {'; '.join(fields.red_flags[:3])}."
        if triggered
        else "Listing data appears internally consistent."
    )
    return RuleResult(rule_id="R08_implausible_listing_data", triggered=triggered, weight=0.20, explanation=explanation)


# ── Rule registry — add new rules here only ──────────────────────────────────

RULES = [
    rule_high_amount,
    rule_missing_invoice_date,
    rule_urgency_language,
    rule_llm_red_flags,
    rule_missing_counterparty,
    rule_crypto_payment_in_chat,
    rule_micro_cap_token,
    rule_implausible_listing_data,
]
