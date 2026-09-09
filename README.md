# Fact Knowledge Layer

A prototype that turns arbitrary text-layer PDFs into grounded, comparable facts and explains relationships between facts.

## Architecture

PDF -> page/chunk ingestion -> deterministic candidate extraction -> normalization -> optional Ollama structuring -> SQLite -> TF-IDF/optional sentence-transformer matching -> Ollama reconciliation -> Streamlit UI.

The prototype is deliberately schema-light. Metric-specific information lives in `attributes` JSON.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Optional local LLM
ollama pull llama3.1:8b

streamlit run app.py
```

Upload one or more text-layer PDFs in the UI.

## CLI demo

```bash
python run_demo.py path/to/report1.pdf path/to/report2.pdf
```

The CLI prints extracted facts and relation candidates with source pages.

## Notes

- No OCR is included; scanned/image-only PDFs are flagged.
- Table extraction uses pdfplumber and assigns lower confidence when structure is ambiguous.
- If Ollama is unavailable, extraction still works heuristically and matching uses TF-IDF.
- If `sentence-transformers` is installed, the matcher automatically uses a local embedding model.
- LLM outputs are JSON-validated and never become the source of truth for grounding: source text/page/offsets always come from ingestion.
