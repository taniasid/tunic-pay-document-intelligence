"""
Scoring layer.

Runs all registered rules against an ExtractedFields object and
produces a composite risk score, label, and summary.
"""

from __future__ import annotations
from pipeline.models import ExtractedFields, RuleResult, RISK_LABELS
from rules.rules_v1 import RULES, RULE_SET_VERSION


def score(fields: ExtractedFields) -> tuple[list[RuleResult], float, RISK_LABELS, str]:
    """
    Run all rules and return:
      (rule_results, risk_score, risk_label, summary)

    risk_score is clamped to [0.0, 1.0].
    Partial failure: if a single rule raises, it's caught and a warning
    RuleResult is appended — other rules still run.
    """
    results: list[RuleResult] = []

    for rule_fn in RULES:
        try:
            results.append(rule_fn(fields))
        except Exception as exc:   # noqa: BLE001
            results.append(RuleResult(
                rule_id=rule_fn.__name__,
                triggered=False,
                weight=0.0,
                explanation=f"Rule evaluation error: {exc}",
            ))

    raw_score = sum(r.weight for r in results if r.triggered)
    risk_score = round(min(raw_score, 1.0), 3)

    risk_label = _label(risk_score)
    summary = _summarise(fields, results, risk_score, risk_label)

    return results, risk_score, risk_label, summary


def _label(score: float) -> RISK_LABELS:
    if score < 0.30:
        return "low"
    if score < 0.60:
        return "medium"
    return "high"


def _summarise(
    fields: ExtractedFields,
    results: list[RuleResult],
    score: float,
    label: RISK_LABELS,
) -> str:
    triggered = [r for r in results if r.triggered]

    if not triggered:
        return (
            f"No risk rules triggered on this {fields.category.replace('_', ' ')}. "
            f"Risk score: {score:.2f} ({label})."
        )

    top = triggered[0]
    others = len(triggered) - 1
    tail = f" ({others} further rule{'s' if others != 1 else ''} also triggered)." if others else "."

    doc_type = fields.category.replace("_", " ")
    entity = fields.entity_name or "Unknown entity"

    return (
        f"{entity} — {doc_type} flagged as {label.upper()} risk (score {score:.2f}). "
        f"Primary concern: {top.explanation}{tail}"
    )
