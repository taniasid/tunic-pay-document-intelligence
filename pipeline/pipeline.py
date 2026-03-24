"""
Pipeline orchestrator.

Wires together: ingest → extract → score → DocumentResult.
Call `run_pipeline(file_bytes, filename, api_key)` and get back a
fully-populated DocumentResult (or raise IngestError for user-fixable problems).
"""

from __future__ import annotations
import time
from pipeline.ingest import ingest_file, FilePayload
from pipeline.extract import extract, MODEL
from pipeline.score import score
from pipeline.models import DocumentResult, ProcessingMetadata
from rules.rules_v1 import RULE_SET_VERSION


def run_pipeline(file_bytes: bytes, filename: str, api_key: str) -> DocumentResult:
    """
    Full pipeline: file bytes → DocumentResult.

    IngestError is re-raised for the UI to surface.
    All other failures are caught and surfaced as warnings in the result.
    """
    # 1. Ingest (may raise IngestError — intentional, let the caller handle it)
    payload: FilePayload = ingest_file(file_bytes, filename)

    # 2. Extract
    t0 = time.time()
    fields, extraction_warnings = extract(payload, api_key)
    latency_ms = int((time.time() - t0) * 1000)

    # 3. Score (may produce partial results; never raises)
    scoring_rules, risk_score, risk_label, summary = score(fields)

    return DocumentResult(
        file_id=payload.file_id,
        category=fields.category,
        category_confidence=fields.category_confidence,
        extracted_fields=fields,
        scoring_rules=scoring_rules,
        risk_score=risk_score,
        risk_label=risk_label,
        summary=summary,
        processing_metadata=ProcessingMetadata(
            model_used=MODEL,
            latency_ms=latency_ms,
            extraction_warnings=extraction_warnings,
            rule_set_version=RULE_SET_VERSION,
        ),
    )
