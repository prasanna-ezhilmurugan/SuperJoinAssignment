# Fact Knowledge Layer — Architecture Design

## 1. Problem framing

Given arbitrary PDFs (financial filings, macro reports, presentations), produce facts that are:
- **grounded** — every fact traces to a page/snippet in a specific source document,
- **comparable** — facts about "the same real thing" from different documents can be found and related,
- **explained** — when two facts look related, the system says whether they corroborate, contradict, or
  are reconcilable, and why.

The system must not hardcode filenames, metrics, or document structure — it has to work on PDFs it has
never seen (financial reports, but also, ideally, anything with numeric/semantic claims in prose or tables).

## 2. Why hybrid (heuristics + LLM), not either alone

- **Pure regex/heuristics** is fast, cheap, fully offline, and auditable, but it can't judge whether two
  differently-worded facts are "the same fact," and it can't explain a contradiction (e.g. distinguishing
  "different metric" from "genuine restatement").
- **Pure LLM extraction** (dump each page to an LLM and ask for facts) generalizes well but is expensive at
  scale, non-deterministic, and — critically — harder to *ground*: an LLM asked to "find facts" tends to
  paraphrase or merge context, making it easy to lose the exact source span.
- **Hybrid**: heuristics do the cheap, deterministic, high-recall job of finding *candidate* fact
  spans with exact page/char grounding. The LLM is only invoked on small, already-grounded snippets to (a)
  label what the fact *is* (metric, scope, entity) when heuristics are ambiguous, and (b) reason over
  *pairs/clusters* of candidate facts to classify their relationship. This keeps the LLM's job close to
  "read these two grounded quotes and judge them" rather than "hallucinate facts from a whole document."

## 3. Pipeline overview

```
PDF(s)
  │
  ▼
[1] Ingestion & chunking ──────────────────────────────────────────────
  │  pdfplumber: per-page text + per-page tables (as structured rows)
  │  chunk = (doc_id, page_no, chunk_id, text, bbox, is_table)
  ▼
[2] Candidate fact extraction (heuristic, deterministic) ──────────────
  │  regex over numbers+units+dates → candidate FactCandidate objects
  │  table rows → structured candidates (row label = metric, column = period)
  │  each candidate carries: raw span, char offsets, page, surrounding
  │  context window (±1-2 sentences) for grounding
  ▼
[3] Normalization ──────────────────────────────────────────────────────
  │  units → canonical (Cr→×1e7 INR, Mn/Bn, %, days, tons…)
  │  periods → canonical (FY24, Q4 FY24, "as of Mar '24" → ISO ranges)
  │  entity/metric label = nearest heading / table row label / left-context noun phrase
  ▼
[4] LLM structuring (only where heuristics are ambiguous or a table needs
     row/column semantics fixed) ──────────────────────────────────────
  │  input: the grounded snippet + surrounding context, never the whole page
  │  output: strict JSON {metric, entity, value, unit, scope/period, direction,
  │           confidence, needs_review}
  ▼
[5] Fact store (flexible schema) ───────────────────────────────────────
  │  SQLite: documents, facts (core cols + JSON `attributes`), fact_relations
  ▼
[6] Candidate matching across facts ────────────────────────────────────
  │  embed "metric + entity + scope" string per fact → vector index
  │  nearest-neighbour search (cosine) → candidate pairs/clusters worth comparing
  │  (avoids O(n²) LLM calls — only plausible matches go to the LLM)
  ▼
[7] LLM reconciliation ──────────────────────────────────────────────────
  │  input: 2+ grounded fact snippets (with metadata: doc, page, period, unit)
  │  output: relation ∈ {corroborates, contradicts, reconcilable_context, unrelated}
  │           + natural-language explanation citing the specific values/scopes
  ▼
[8] UI (Streamlit) ───────────────────────────────────────────────────────
     upload → pipeline runs → facts table, fact detail w/ highlighted source,
     relations view (grouped by type), "needs review" / low-confidence queue
```

## 4. Data model (deliberately schema-light)

Rigid columns only for what's *always* true of a fact; everything metric-specific goes in a JSON blob so
the schema can grow without migrations — this is what lets the system handle document types it wasn't
designed for.

```
Document(doc_id, filename, title, uploaded_at, page_count)

Fact(
  fact_id,
  doc_id, page_no, char_start, char_end,     -- grounding
  raw_text,                                   -- exact source snippet
  context_text,                               -- ± surrounding sentences, for LLM + UI
  metric_label,                               -- e.g. "Adjusted EBITDA", "Net Working Capital days"
  entity,                                     -- e.g. "Delhivery Limited", nullable
  value_numeric, unit, value_raw_text,        -- normalized + original, e.g. 76, "INR_CR", "₹76Cr"
  period_label, period_start, period_end,     -- e.g. "FY24", 2023-04-01, 2024-03-31
  extraction_method,                          -- "regex" | "table" | "llm"
  confidence,                                 -- 0-1, heuristic- or LLM-assigned
  attributes JSON,                            -- open-ended: {"margin_pct": 1.6, "yoy": "12.7%"} etc.
  needs_review BOOLEAN
)

FactRelation(
  relation_id,
  fact_id_a, fact_id_b,
  relation_type,        -- corroborates | contradicts | reconcilable_context | unrelated
  explanation,           -- LLM-authored, must cite fact values/scopes, not invent new ones
  confidence,
  created_by             -- "heuristic_match+llm" for audit
)
```

## 5. Matching strategy (how we find what to compare)

1. Build a short "matching key" text per fact: `f"{metric_label} | {entity or ''} | {period_label or ''}"`.
2. Embed all matching keys (a small local embedding model or a single batched embedding API call).
3. For each fact, retrieve top-k nearest neighbours *from other documents* (cosine similarity above a
   threshold) — these are candidate pairs, not confirmed relations.
4. Also add same-document, different-section pairs sharing a metric_label but different period_label —
   this is how we catch things like "director active in the board section, resigned in a later filing
   note" or self-inconsistency within one document.
5. Only these candidate pairs go to the LLM reconciliation step (bounds the number of LLM calls to
   roughly O(n·k), not O(n²)).

## 6. LLM reconciliation prompt contract

The LLM never sees raw documents — only pre-grounded fact pairs. This bounds hallucination risk and keeps
answers auditable:

- Input: fact A and fact B, each with `raw_text`, `context_text`, `doc`, `page`, `period_label`, `unit`,
  `value_numeric`.
- Instruction: classify the relation and explain *using only the given values*; if scope/unit/time differs
  in a way that would explain a numeric mismatch, say so explicitly (this is what produces case #3 —
  reconcilable-through-context).
- Output: strict JSON, so the UI can render it without re-parsing prose.
- If the LLM's own confidence is low or the inputs are too different to compare meaningfully, it must
  return `unrelated` rather than force a relation — this is the main lever against false contradictions.

## 7. Illustration with the starter dataset (what the four required cases look like here)

*(To be filled in with real extracted evidence once the pipeline runs — sketching the expected shape now
based on documents already skimmed.)*

1. **Corroborated across documents**: Delhivery's FY24 "revenue from services" (₹8,142 Cr) appears in the
   Q4 FY24 earnings presentation's headline slide and again in its detailed P&L table — same fact, two
   expressions (rounded highlight vs. exact table row), same period → `corroborates`.
2. **Genuine/likely contradiction**: worth checking whether the Annual Report FY24 and the Q4 earnings
   presentation state different EBITDA or PAT figures for the same period (e.g. due to one being
   standalone vs. consolidated, or a later restatement) — flagged for the LLM to determine if it's a real
   discrepancy or explainable.
3. **Apparent contradiction explained by context**: the earnings deck shows both "EBITDA" (₹127 Cr, 1.6%
   margin) and "Adjusted EBITDA" (₹76 Cr, 0.9% margin) for FY24 — naively these look like conflicting
   profitability claims for the "same" year, but they're different, clearly-defined metrics (Adjusted
   EBITDA excludes ESOP expense, adds back lease rent, etc.) → `reconcilable_context`, not a contradiction.
4. **Extraction/reasoning failure**: table-heavy pages (e.g. the macroeconomic appendix tables in the RBI
   annual report) are the likely failure mode — multi-row, multi-column tables where regex can grab a
   number but attribute it to the wrong row/column label without table-structure-aware parsing. Planned
   handling: mark low-confidence table extractions as `needs_review` rather than silently emitting a
   wrong fact, and prefer pdfplumber's table-extraction mode (which returns row/column structure) over
   plain-text regex wherever a page is detected as tabular.

## 8. Incrementality & scale (brownie points)

- **New PDF added later**: only its own chunks are processed; its facts are embedded and matched against
  the *existing* vector index (nearest-neighbour search), not against every fact in the system — no
  reprocessing of prior documents.
- **Large PDFs**: page-by-page streaming extraction (never load the whole PDF into memory as one string);
  regex/table pass is O(pages); only ambiguous spans go to the LLM, capping LLM cost independent of PDF
  size.
- **Many PDFs**: the vector index (e.g. a simple FAISS/numpy cosine index) makes matching sub-linear;
  heuristic candidate generation is embarrassingly parallel across documents.
- **Schema evolution**: the `attributes` JSON column plus `metric_label` being free text (not an enum)
  means new kinds of facts (e.g. a board member's tenure dates, a pin-code count, a debt/equity ratio)
  don't require a schema migration — the UI groups/filters by whatever `metric_label`s actually appear.

## 9. What "done" looks like for the prototype

- Upload endpoint/UI accepts any PDF, no filename/schema assumptions in code.
- Facts table shows: metric, entity, value+unit, period, source (doc/page), confidence, with a link to the
  highlighted snippet.
- A relations view lists the four case types with the two source snippets side-by-side and the LLM's
  explanation.
- A "needs review" queue surfaces low-confidence extractions and unresolved candidate pairs (transparency
  about failure modes, per case #4 requirement).

## 10. Explicit trade-offs / non-goals for this prototype

- No OCR for scanned/image-only PDFs (text-layer PDFs only) — flagged as a known limitation, not solved.
- No cross-lingual matching.
- Matching threshold tuning is heuristic (a fixed cosine cutoff), not learned — acceptable for a
  prototype, called out as a place a real system would need calibration/eval data.
- LLM calls assume an API key is available at runtime; the extraction layer works standalone (heuristics
  only) if no key is present, just without relation reasoning — degrades gracefully.

---
Next step: implement `ingest.py` (chunking), `extract.py` (heuristics + normalization), `match.py`
(embedding index), `reconcile.py` (LLM calls), `store.py` (SQLite), and a `app.py` Streamlit UI wiring
these together, plus a `run_demo.py` that processes the starter dataset and prints the four required cases
with evidence.
