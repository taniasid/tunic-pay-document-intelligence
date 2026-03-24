"""
Output contract schemas. Every field that may not apply to a given
document category is Optional and defaults to None so the schema
stays consistent across all file types.
"""

from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


CATEGORIES = Literal[
    "invoice",
    "marketplace_listing_screenshot",
    "chat_screenshot",
    "website_screenshot",
    "other",
]

RISK_LABELS = Literal["low", "medium", "high", "review_needed"]


class ExtractedFields(BaseModel):
    entity_name: Optional[str] = None          # Primary named entity (seller, sender, issuer)
    amount: Optional[float] = None             # Primary monetary amount
    currency: Optional[str] = None             # ISO 4217 or token symbol
    date: Optional[str] = None                 # ISO 8601 date string where present
    counterparty: Optional[str] = None         # Buyer, recipient, or other party
    platform: Optional[str] = None             # Marketplace / exchange / app name
    contact_details: Optional[str] = None      # Phone, email, username
    red_flags: list[str] = Field(default_factory=list)   # LLM-identified anomalies
    urgency_language_detected: bool = False    # True if pressure/urgency language found
    category: CATEGORIES = "other"
    category_confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class RuleResult(BaseModel):
    rule_id: str
    triggered: bool
    weight: float          # Contribution to composite score when triggered
    explanation: str       # Human-readable reason


class ProcessingMetadata(BaseModel):
    model_used: str
    latency_ms: int
    extraction_warnings: list[str] = Field(default_factory=list)
    rule_set_version: str = "v1"


class DocumentResult(BaseModel):
    file_id: str
    category: CATEGORIES
    category_confidence: float
    extracted_fields: ExtractedFields
    scoring_rules: list[RuleResult]
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_label: RISK_LABELS
    summary: str
    processing_metadata: ProcessingMetadata
