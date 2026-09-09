import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

def key(f):
    return " | ".join(str(x or "") for x in [f.get("metric_label"),f.get("entity"),f.get("period_label"),f.get("unit")])

class Matcher:
    def __init__(self, threshold=0.38, model_name="all-MiniLM-L6-v2"):
        self.threshold=threshold
        self.model=None
        if SentenceTransformer:
            try: self.model=SentenceTransformer(model_name)
            except Exception: self.model=None

    def candidates(self, facts, top_k=5):
        if len(facts)<2: return []
        texts=[key(f) for f in facts]
        if self.model:
            X=np.asarray(self.model.encode(texts,normalize_embeddings=True))
            sim=X @ X.T
        else:
            X=TfidfVectorizer(ngram_range=(1,2),min_df=1).fit_transform(texts)
            sim=cosine_similarity(X)
        pairs=[]
        for i,a in enumerate(facts):
            scores=[]
            for j,b in enumerate(facts):
                if i==j or a["doc_id"]==b["doc_id"]: continue
                s=float(sim[i,j])
                if s>=self.threshold: scores.append((s,j))
            for s,j in sorted(scores,reverse=True)[:top_k]:
                pair=tuple(sorted((i,j)))
                if pair not in {p[0] for p in pairs}: pairs.append((pair,s))
        # Same-document metric matches across periods/sections.
        for i,a in enumerate(facts):
            for j in range(i+1,len(facts)):
                b=facts[j]
                if a["doc_id"]==b["doc_id"] and a.get("metric_label") and a["metric_label"].lower()==str(b.get("metric_label") or "").lower():
                    pairs.append(((i,j),0.99))
        return pairs
