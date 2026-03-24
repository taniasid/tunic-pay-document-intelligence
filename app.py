"""
Tunic Pay — Document Risk Analyser
Streamlit UI: upload a document, see extracted fields and risk score side by side.
"""

import json
import os
import sys

# Allow imports from project root
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

from pipeline.ingest import IngestError
from pipeline.pipeline import run_pipeline

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Tunic Pay · Document Risk Analyser",
    page_icon="🔍",
    layout="wide",
)

# ── Styling ────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
h1, h2, h3 { font-family: 'IBM Plex Mono', monospace; letter-spacing: -0.02em; }

.risk-high   { background:#fee2e2; color:#991b1b; border:1px solid #fca5a5; padding:6px 14px; border-radius:4px; font-weight:600; font-family:'IBM Plex Mono',monospace; display:inline-block; }
.risk-medium { background:#fef3c7; color:#92400e; border:1px solid #fcd34d; padding:6px 14px; border-radius:4px; font-weight:600; font-family:'IBM Plex Mono',monospace; display:inline-block; }
.risk-low    { background:#d1fae5; color:#065f46; border:1px solid #6ee7b7; padding:6px 14px; border-radius:4px; font-weight:600; font-family:'IBM Plex Mono',monospace; display:inline-block; }
.risk-review { background:#ede9fe; color:#4c1d95; border:1px solid #c4b5fd; padding:6px 14px; border-radius:4px; font-weight:600; font-family:'IBM Plex Mono',monospace; display:inline-block; }

.rule-triggered { background:#fee2e2; border-left:3px solid #ef4444; padding:8px 12px; margin:4px 0; border-radius:0 4px 4px 0; font-size:0.88rem; }
.rule-clean     { background:#f9fafb; border-left:3px solid #d1d5db; padding:8px 12px; margin:4px 0; border-radius:0 4px 4px 0; font-size:0.88rem; color:#6b7280; }

.score-bar-outer { background:#e5e7eb; border-radius:8px; height:18px; width:100%; margin:8px 0; }
.summary-box { background:#1e293b; color:#e2e8f0; border-radius:8px; padding:16px 20px; font-family:'IBM Plex Mono',monospace; font-size:0.85rem; line-height:1.6; margin-bottom:16px; }
.field-row { display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding:6px 0; font-size:0.9rem; }
.field-key { color:#64748b; font-weight:600; min-width:170px; }
.field-val { color:#1e293b; text-align:right; word-break:break-all; }
.warning-box { background:#fffbeb; border:1px solid #fcd34d; border-radius:6px; padding:10px 14px; font-size:0.85rem; margin:8px 0; }
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────────

st.markdown("# 🔍 Document Risk Analyser")
st.markdown("Upload an invoice, marketplace listing, chat screenshot, or website screenshot to extract structured fields and compute a fraud risk score.")
st.divider()

# ── Sidebar — API key ──────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Configuration")
    api_key = st.text_input(
        "OpenRouter API Key",
        type="password",
        value=os.environ.get("OPENROUTER_API_KEY", ""),
        help="Your OpenRouter API key (never stored).",
    )
    st.markdown("---")
    st.markdown("**Supported formats**")
    st.markdown("PDF · PNG · JPEG · WebP")
    st.markdown("**Max file size:** 20 MB")
    st.markdown("---")
    st.markdown("**Categories**")
    for cat in ["invoice", "marketplace_listing_screenshot", "chat_screenshot", "website_screenshot", "other"]:
        st.markdown(f"- `{cat}`")

# ── File uploader ──────────────────────────────────────────────────────────────

uploaded = st.file_uploader(
    "Drop a file to analyse",
    type=["pdf", "png", "jpg", "jpeg", "webp"],
    label_visibility="collapsed",
)

if not api_key:
    st.info("Enter your OpenRouter API key in the sidebar to get started.")
    st.stop()

if not uploaded:
    st.stop()

# ── Process ────────────────────────────────────────────────────────────────────

with st.spinner("Extracting and scoring…"):
    try:
        result = run_pipeline(uploaded.read(), uploaded.name, api_key)
    except IngestError as exc:
        st.error(f"**File error:** {exc}")
        st.stop()
    except Exception as exc:
        st.error(f"**Unexpected error:** {exc}")
        st.stop()

# ── Layout: two columns ────────────────────────────────────────────────────────

left, right = st.columns([1, 1], gap="large")

# ── LEFT: Extracted fields ─────────────────────────────────────────────────────

with left:
    st.markdown("### Extracted Fields")

    conf_pct = int(result.category_confidence * 100)
    st.markdown(
        f"**Category:** `{result.category}` "
        f"<span style='color:#64748b;font-size:0.85rem'>({conf_pct}% confidence)</span>",
        unsafe_allow_html=True,
    )

    fields = result.extracted_fields

    def _row(label: str, value) -> str:
        if value is None or value == [] or value == "":
            val_html = "<span style='color:#cbd5e1;font-style:italic'>—</span>"
        elif isinstance(value, list):
            val_html = "<br>".join(f"• {v}" for v in value)
        elif isinstance(value, bool):
            colour = "#ef4444" if value else "#10b981"
            val_html = f"<span style='color:{colour};font-weight:600'>{'Yes' if value else 'No'}</span>"
        else:
            val_html = str(value)
        return f"<div class='field-row'><span class='field-key'>{label}</span><span class='field-val'>{val_html}</span></div>"

    rows_html = "".join([
        _row("Entity name", fields.entity_name),
        _row("Amount", f"{fields.amount:,.2f} {fields.currency or ''}" if fields.amount else None),
        _row("Date", fields.date),
        _row("Counterparty", fields.counterparty),
        _row("Platform", fields.platform),
        _row("Contact details", fields.contact_details),
        _row("Urgency language", fields.urgency_language_detected),
        _row("LLM red flags", fields.red_flags if fields.red_flags else None),
    ])

    st.markdown(rows_html, unsafe_allow_html=True)

    if result.processing_metadata.extraction_warnings:
        for w in result.processing_metadata.extraction_warnings:
            st.markdown(f"<div class='warning-box'>⚠️ {w}</div>", unsafe_allow_html=True)

    with st.expander("Raw JSON output"):
        st.code(result.model_dump_json(indent=2), language="json")

# ── RIGHT: Risk score ──────────────────────────────────────────────────────────

with right:
    st.markdown("### Risk Assessment")

    label = result.risk_label
    css_class = {
        "high": "risk-high",
        "medium": "risk-medium",
        "low": "risk-low",
        "review_needed": "risk-review",
    }.get(label, "risk-low")

    score_pct = int(result.risk_score * 100)

    bar_colour = {"high": "#ef4444", "medium": "#f59e0b", "low": "#10b981", "review_needed": "#8b5cf6"}.get(label, "#10b981")

    st.markdown(
        f"<div style='display:flex;align-items:center;gap:16px;margin-bottom:8px'>"
        f"  <span class='{css_class}'>{label.upper().replace('_', ' ')}</span>"
        f"  <span style='font-size:2rem;font-family:IBM Plex Mono,monospace;font-weight:600'>{result.risk_score:.2f}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<div class='score-bar-outer'>"
        f"  <div style='background:{bar_colour};width:{score_pct}%;height:100%;border-radius:8px;transition:width 0.4s'></div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown(f"<div class='summary-box'>{result.summary}</div>", unsafe_allow_html=True)

    st.markdown("#### Scoring Rules")
    for rule in sorted(result.scoring_rules, key=lambda r: -r.weight):
        css = "rule-triggered" if rule.triggered else "rule-clean"
        icon = "🔴" if rule.triggered else "⚪"
        weight_str = f"weight {rule.weight:.2f}"
        st.markdown(
            f"<div class='{css}'>"
            f"  {icon} <strong>{rule.rule_id}</strong> <span style='float:right;color:#94a3b8;font-size:0.8rem'>{weight_str}</span><br>"
            f"  <span style='color:#475569'>{rule.explanation}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    meta = result.processing_metadata
    st.markdown(
        f"<span style='font-size:0.78rem;color:#94a3b8'>"
        f"Model: `{meta.model_used}` · "
        f"Latency: {meta.latency_ms} ms · "
        f"Rules: `{meta.rule_set_version}`"
        f"</span>",
        unsafe_allow_html=True,
    )