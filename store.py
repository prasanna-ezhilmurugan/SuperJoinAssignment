import json, sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
 doc_id TEXT PRIMARY KEY, filename TEXT NOT NULL, title TEXT, uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP, page_count INTEGER
);
CREATE TABLE IF NOT EXISTS facts(
 fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
 doc_id TEXT, page_no INTEGER, char_start INTEGER, char_end INTEGER,
 raw_text TEXT, context_text TEXT, metric_label TEXT, entity TEXT,
 value_numeric REAL, unit TEXT, value_raw_text TEXT,
 period_label TEXT, period_start TEXT, period_end TEXT,
 extraction_method TEXT, confidence REAL, attributes TEXT, needs_review INTEGER,
 FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
);
CREATE TABLE IF NOT EXISTS fact_relations(
 relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 fact_id_a INTEGER, fact_id_b INTEGER, relation_type TEXT,
 explanation TEXT, confidence REAL, created_by TEXT,
 UNIQUE(fact_id_a,fact_id_b)
);
"""

class Store:
    def __init__(self, db_path="storage/facts.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path=db_path
        with sqlite3.connect(db_path) as con: con.executescript(SCHEMA)

    def add_document(self, doc_id, filename, title, page_count):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?)",
                        (doc_id,filename,title,__import__("datetime").datetime.now().isoformat(),page_count))

    def add_facts(self, facts):
        with sqlite3.connect(self.db_path) as con:
            ids=[]
            for f in facts:
                cur=con.execute("""INSERT INTO facts
                (doc_id,page_no,char_start,char_end,raw_text,context_text,metric_label,entity,
                 value_numeric,unit,value_raw_text,period_label,period_start,period_end,
                 extraction_method,confidence,attributes,needs_review)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (f.doc_id,f.page_no,f.char_start,f.char_end,f.raw_text,f.context_text,
                  f.metric_label,f.entity,f.value_numeric,f.unit,f.value_raw_text,f.period_label,
                  f.period_start,f.period_end,f.extraction_method,f.confidence,
                  json.dumps(f.attributes,ensure_ascii=False),int(f.needs_review)))
                ids.append(cur.lastrowid)
        return ids

    def facts_df(self):
        import pandas as pd
        with sqlite3.connect(self.db_path) as con:
            return pd.read_sql_query("""SELECT f.*, d.filename FROM facts f JOIN documents d USING(doc_id)
                                        ORDER BY f.doc_id,f.page_no,f.fact_id""",con)

    def get_facts(self):
        import pandas as pd
        with sqlite3.connect(self.db_path) as con:
            return pd.read_sql_query("SELECT * FROM facts ORDER BY fact_id",con).to_dict("records")

    def add_relation(self,a,b,typ,explanation,confidence,created_by="heuristic_match+llm"):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""INSERT OR REPLACE INTO fact_relations
            (fact_id_a,fact_id_b,relation_type,explanation,confidence,created_by)
            VALUES(?,?,?,?,?,?)""",(a,b,typ,explanation,confidence,created_by))

    def relations_df(self):
        import pandas as pd
        with sqlite3.connect(self.db_path) as con:
            return pd.read_sql_query("""SELECT r.*, da.filename doc_a, db.filename doc_b,
              fa.raw_text raw_a, fb.raw_text raw_b, fa.page_no page_a, fb.page_no page_b
              FROM fact_relations r JOIN facts fa ON fa.fact_id=r.fact_id_a
              JOIN facts fb ON fb.fact_id=r.fact_id_b
              JOIN documents da ON da.doc_id=fa.doc_id JOIN documents db ON db.doc_id=fb.doc_id
              ORDER BY r.relation_id DESC""",con)
