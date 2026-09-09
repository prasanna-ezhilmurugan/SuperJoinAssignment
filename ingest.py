import hashlib, re
from pathlib import Path
import pdfplumber
from models import Chunk

def make_doc_id(path: str) -> str:
    p = Path(path)
    stat = p.stat()
    raw = f"{p.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]

def _sentence_spans(text):
    # Conservative sentence splitter; offsets remain exact against page text.
    for m in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", text):
        s = m.group().strip()
        if s:
            start = m.start() + len(m.group()) - len(m.group().lstrip())
            yield start, start + len(s), s

def context_window(text, start, end, radius=2):
    spans = list(_sentence_spans(text))
    idx = 0
    for i, (s,e,_) in enumerate(spans):
        if s <= start <= e or s <= end <= e:
            idx = i; break
    lo, hi = max(0, idx-radius), min(len(spans), idx+radius+1)
    if spans:
        return text[spans[lo][0]:spans[hi-1][1]]
    return text[max(0,start-300):min(len(text),end+300)]

def ingest_pdf(path: str):
    path = str(path)
    doc_id = make_doc_id(path)
    chunks = []
    page_count = 0
    has_text = False
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            if text.strip():
                has_text = True
                chunks.append(Chunk(doc_id, page_no, f"{doc_id}-p{page_no}-text",
                                    text, 0, len(text), is_table=False))
            for ti, table in enumerate(tables):
                rows = []
                for row in table:
                    vals = [str(x).strip() if x is not None else "" for x in row]
                    rows.append(" | ".join(vals))
                t = "\n".join(rows).strip()
                if t:
                    chunks.append(Chunk(doc_id, page_no, f"{doc_id}-p{page_no}-t{ti}",
                                        t, 0, len(t), is_table=True))
    return doc_id, page_count, chunks, has_text
