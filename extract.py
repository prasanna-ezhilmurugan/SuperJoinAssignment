import re, math
from models import FactCandidate

NUMBER_RE = re.compile(
    r"(?P<currency>₹|Rs\.?|INR|USD|EUR|\$|€)?\s*"
    r"(?P<num>\(?[-+]?\d[\d,]*(?:\.\d+)?\)?(?:\s*[-–]\s*\d[\d,]*(?:\.\d+)?)?)"
    r"\s*(?P<unit>%|percent|percentage|Cr\.?|crore(?:s)?|Mn|million|Bn|billion|days?|tons?|tonnes?|kg|\b)?",
    re.I
)
PERIOD_RE = re.compile(
    r"\b(Q[1-4]\s*)?(FY\s*\d{2,4}|20\d{2}|19\d{2})(?:[-/](?:\d{2,4}))?\b|"
    r"\b(?:as of|at|on)\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
    re.I
)
HEADING_RE = re.compile(r"^\s{0,3}([A-Z][A-Za-z0-9 &()/,-]{3,80})\s*$")

UNIT_SCALE = {
    "cr": ("INR_CR", 1.0), "crore": ("INR_CR", 1.0), "crores": ("INR_CR", 1.0),
    "mn": ("MN", 1.0), "million": ("MN", 1.0), "bn": ("BN", 1.0), "billion": ("BN", 1.0),
    "%": ("PCT", 1.0), "percent": ("PCT", 1.0), "percentage": ("PCT", 1.0),
    "day": ("DAYS", 1.0), "days": ("DAYS", 1.0), "ton": ("TONS", 1.0),
    "tons": ("TONS", 1.0), "tonne": ("TONS", 1.0), "tonnes": ("TONS", 1.0),
    "kg": ("KG", 1.0)
}

def parse_num(s):
    s = s.strip().replace(",", "")
    if "-" in s[1:]:
        parts = re.split(r"\s*[-–]\s*", s)
        try: return sum(float(p.strip("()")) for p in parts) / len(parts)
        except: return None
    try: return float(s.strip("()"))
    except: return None

def normalize_value(num, currency, unit):
    u = (unit or "").strip().lower().rstrip(".")
    if u in UNIT_SCALE:
        return num, UNIT_SCALE[u][0]
    c = (currency or "").lower()
    if c in ("₹", "rs", "rs.", "inr"):
        return num, "INR"
    if c in ("$", "usd"):
        return num, "USD"
    if c in ("€", "eur"):
        return num, "EUR"
    return num, ""

def nearest_label(text, start):
    before = text[:start]
    lines = before.splitlines()
    for line in reversed(lines[-5:]):
        line = line.strip(" |\t")
        if not line: continue
        if HEADING_RE.match(line):
            return line[:120]
        # Table row labels: text before first numeric-looking token.
        candidate = re.split(r"\s{2,}|\|", line)[0].strip()
        if candidate and not re.search(r"\d", candidate) and 2 <= len(candidate.split()) <= 12:
            return candidate
    # Noun phrase immediately before the number.
    window = before[-140:]
    m = re.search(r"([A-Za-z][A-Za-z &()/,-]{2,80})\s*[:=]?\s*$", window)
    return m.group(1).strip() if m else "Unlabelled numeric claim"

def period_info(context):
    m = PERIOD_RE.search(context)
    if not m: return None, None, None
    label = m.group(0)
    year_m = re.search(r"(20\d{2}|19\d{2})", label)
    if year_m:
        y = int(year_m.group(1))
        if "FY" in label.upper():
            # Indian-style FY approximation; preserves label and gives useful range.
            return label, f"{y-1}-04-01", f"{y}-03-31"
        return label, f"{y}-01-01", f"{y}-12-31"
    return label, None, None

def extract_candidates(doc_id, page_no, text, is_table=False):
    out = []
    for m in NUMBER_RE.finditer(text):
        num = parse_num(m.group("num"))
        if num is None or not math.isfinite(num):
            continue
        raw = m.group(0).strip()
        # Ignore tiny standalone page numbers / bullets.
        if not (m.group("unit") or m.group("currency")) and abs(num) < 1:
            continue
        ctx = text[max(0, m.start()-250):min(len(text), m.end()+300)]
        label = nearest_label(text, m.start())
        period_label, ps, pe = period_info(ctx)
        unit, norm = normalize_value(num, m.group("currency"), m.group("unit"))
        # Correct variable assignment: norm is canonical unit.
        canonical_unit = norm or unit
        conf = 0.72 if (m.group("unit") or m.group("currency")) else 0.48
        if is_table: conf -= 0.08
        if label == "Unlabelled numeric claim": conf -= 0.12
        out.append(FactCandidate(
            doc_id=doc_id, page_no=page_no, raw_text=raw, context_text=ctx,
            char_start=m.start(), char_end=m.end(), metric_label=label,
            value_numeric=num, unit=canonical_unit, value_raw_text=raw,
            period_label=period_label, period_start=ps, period_end=pe,
            extraction_method="table" if is_table else "regex",
            confidence=max(0.0, min(1.0, conf)),
            needs_review=conf < 0.55
        ))
    return dedupe(out)

def dedupe(facts):
    seen = set(); out=[]
    for f in facts:
        key=(f.doc_id,f.page_no,f.char_start,f.char_end,f.metric_label,f.value_numeric,f.unit)
        if key not in seen:
            seen.add(key); out.append(f)
    return out

def extract_from_chunks(chunks):
    facts=[]
    for c in chunks:
        facts.extend(extract_candidates(c.doc_id,c.page_no,c.text,c.is_table))
    return facts
