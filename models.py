from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import json

@dataclass
class Chunk:
    doc_id: str
    page_no: int
    chunk_id: str
    text: str
    char_start: int = 0
    char_end: int = 0
    bbox: Optional[tuple] = None
    is_table: bool = False

@dataclass
class FactCandidate:
    doc_id: str
    page_no: int
    raw_text: str
    context_text: str
    char_start: int
    char_end: int
    metric_label: str = ""
    entity: Optional[str] = None
    value_numeric: Optional[float] = None
    unit: str = ""
    value_raw_text: str = ""
    period_label: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    extraction_method: str = "regex"
    confidence: float = 0.5
    attributes: dict[str, Any] = field(default_factory=dict)
    needs_review: bool = False
    source_doc: str = ""

    def to_db_dict(self):
        d = asdict(self)
        d["attributes"] = json.dumps(d["attributes"], ensure_ascii=False)
        return d
