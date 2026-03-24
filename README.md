# Tunic Pay — Document Risk Analyser

A prototype pipeline for document categorisation and fraud risk extraction. Accepts unstructured files (invoices, marketplace listings, chat screenshots, website screenshots), extracts structured fields via an LLM, and scores them with deterministic rules to produce a calibrated risk signal.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# Poppler is required for PDF support:
# macOS:  brew install poppler
# Ubuntu: apt-get install poppler-utils

# 2. Set your OpenRouter API key
export OPENROUTER_API_KEY=sk-or-...

# 3. Run the UI
streamlit run app.py

# Or enter the API key in the sidebar after launch
```

Open http://localhost:8501, enter your OpenRouter API key in the sidebar, and upload any supported file.

---

## Architecture

```
app.py                      Streamlit UI — upload, display, layout
pipeline/
  ingest.py                 Validate, resize & normalise files → FilePayload
  extract.py                OpenRouter API call → ExtractedFields (with retry)
  score.py                  Run rule registry → risk score + label
  pipeline.py               Orchestrator: wires ingest → extract → score
  models.py                 Pydantic schemas (the output contract)
rules/
  rules_v1.py               8 independent scoring rules + RULES registry
examples/
  inputs/                   Sample input files
  outputs/                  Example output JSON for all 4 document types
```

The pipeline has exactly 4 stages with no shared state between them. Each stage can be tested independently.

---

## Design Decisions

### API: OpenRouter with `anthropic/claude-opus-4-5`
The pipeline calls OpenRouter's OpenAI-compatible endpoint (`/v1/chat/completions`) using plain `requests` — no SDK dependency. The model was chosen for strong vision capabilities, reliable JSON instruction-following, and low hallucination rate on structured extraction tasks. Any vision-capable model on OpenRouter can be swapped in by changing the `MODEL` constant in `pipeline/extract.py`.

### Image normalisation
All images (PNG, JPEG, WebP) are resized via Pillow before base64 encoding. This keeps payloads well within API limits regardless of original file size and ensures consistent behaviour across all file types. PDFs are are converted to images and then put through the same normalisation step.

### Consistency strategy (LLM non-determinism)
- `temperature=0` eliminates most variance in structured extraction
- JSON-only system prompt with explicit schema leaves no room for conversational drift
- Pydantic validation catches schema violations immediately
- Up to 2 retries on parse/validation failure before falling back to a safe default
- All retry warnings surface in `processing_metadata.extraction_warnings`

### Confidence-gated routing
If `category_confidence < 0.60`, the category is overridden to `"other"` and flagged for human review. Scoring is skipped in this case — a misclassified document would trigger wrong rules.

### Partial failure philosophy
Each layer fails independently. If extraction partially succeeds, the best available result is returned with a warning. The output contract always has all fields present (nulls for missing values) so that `KeyError` is never encountered downstream.

---

## Scoring Rules

All rules live in `rules/rules_v1.py`. Each rule is a standalone function `(ExtractedFields) -> RuleResult`. Adding a new rule means writing one function and appending it to the `RULES` list without modifying existing rules.

The composite score = sum of weights of triggered rules, clamped to `[0, 1]`. Weights are intentionally allowed to sum above 1 so that high-severity rules can dominate without requiring renormalisation when new rules are added.

| Rule ID | Applies To | Weight | Fraud Logic |
|---|---|---|---|
| `R01_high_amount` | all categories | 0.20 | Unusually high amounts for the document type |
| `R02_missing_invoice_date` | invoice | 0.20 | Legitimate invoices always have a date; absence suggests fabrication |
| `R03_urgency_language` | all | 0.25 | Time pressure is the core indicator of social-engineering lever |
| `R04_llm_red_flags` | all | 0.20 | 2+ independent LLM-identified anomalies raise the overall risk profile |
| `R05_missing_counterparty` | invoice, marketplace | 0.10 | Genuine commercial documents identify both parties; missing counterparty is a weak but real signal |
| `R06_crypto_payment_in_chat` | chat_screenshot | 0.30 | Crypto salary promises in informal chat channels are a common indicator of scams |
| `R07_micro_cap_token` | website_screenshot | 0.25 | Micro-cap tokens with very few holders are used for wash-trading and layering in money laundering | 
| `R08_implausible_listing_data` | marketplace | 0.20 | Fabricated listings often contain subtle data errors |

**Risk labels:** `< 0.30` → low · `0.30–0.60` → medium · `> 0.60` → high

---

## Robustness & Edge Cases

**Unsupported file types:** Rejected at ingest with a user-facing message before any API call.

**Oversized files:** 20 MB cap enforced 

**Large images:** All images are resized to prevent API payload limit errors on high-resolution screenshots.

**Corrupt files:** `pdf2image`/Pillow decode errors are caught and surfaced as `IngestError`.

**LLM failures:** Retried up to 2 times. On exhaustion, returns `ExtractedFields(category="other")` with a warning. Scoring still runs on the default fields.

**Schema violations:** Pydantic raises `ValidationError`; treated as a retry trigger.

**Scoring rule crashes:** Each rule is wrapped in `try/except` in the scorer; a failing rule produces a `triggered=False` result with an explanation — other rules are unaffected.

**Multi-page PDFs:** Each page is sent as separate image blocks in a single LLM call with an instruction to synthesise across pages.

**Mixed-category documents** (e.g. a chat screenshot containing an invoice image): The LLM assigns the dominant category. 

**Extending the rule set** In rules/rules_v1.py — write one function, and append it to RULES.

---

## Trade-offs & Future work

- Add a proper test suite: unit tests per rule, tests for extraction (run the pipeline against known files and compare against expected JSON), tests for partially successful runs that suggest improvements for cleaner output
- Rule drift detection: log rule fire rates per document type; alert if a rule fires on the majority of documents (based on pre-defined threshold)
- LLM extraction & summary quality drift detection 
- Async processing: Streamlit's synchronous model blocks the UI during LLM calls; a queue + polling approach would improve perceived performance
- Confidence calibration: improve LLM confidence against labelled data; current outputs are based on self-reported LLM confidence
- Structured outputs: enforce the JSON schema at the API level, removing the need for parse retries 
- Rule versioning with a database: store `(file_id, rule_set_version, risk_score)` tuples so decisions can be re-audited when rules change
- Multi-page summarisation for long PDFs
- Use labelled fraud data to inform better rule weights; weights are currently tuned manually
- compare Claude Opus LLM output with Gemini Flash 1.5 (strong reputation for similar tasks)
- For mixed-category documents, run extraction once per detected category and merge the red flags/aggregate risk scores (currently the system is designed to assign the dominant category)
- generate synthetic data & collect more examples of documents associated to scam/fraud incidents for further validation

