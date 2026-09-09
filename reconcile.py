import json, os, re, requests

RELATIONS={"corroborates","contradicts","reconcilable_context","unrelated"}

SYSTEM_PROMPT = """You are a strict evidence reconciliation engine.
You receive ONLY two or more already-grounded facts. Never invent facts.
Classify their relationship as exactly one of:
corroborates, contradicts, reconcilable_context, unrelated.
Use scope, period, unit, entity, metric definition and value. Different metrics
or scopes that explain different numbers are reconcilable_context, not contradiction.
If the facts are not meaningfully comparable, use unrelated.
Return JSON only:
{"relation_type":"...", "explanation":"...", "confidence":0.0}
The explanation must mention the supplied values/scopes and may not introduce new facts."""
def _prompt(a,b):
    return SYSTEM_PROMPT + "\nFACT A:\n" + json.dumps(a,ensure_ascii=False) + "\nFACT B:\n" + json.dumps(b,ensure_ascii=False)

def heuristic_reconcile(a,b):
    ma=(a.get("metric_label") or "").lower()
    mb=(b.get("metric_label") or "").lower()
    if not ma or not mb: return ("unrelated","Missing metric labels.",0.35)
    if ma==mb and a.get("entity")==b.get("entity") and a.get("period_label")==b.get("period_label"):
        if a.get("unit")==b.get("unit") and a.get("value_numeric") is not None and b.get("value_numeric") is not None:
            av,bv=float(a["value_numeric"]),float(b["value_numeric"])
            rel="corroborates" if abs(av-bv)<=max(0.01,0.03*max(abs(av),abs(bv))) else "contradicts"
            return rel,f"Same metric/scope/period; values are {av:g} and {bv:g}.",0.72
        return "reconcilable_context","Metric and period align, but unit/entity metadata differs or is incomplete.",0.58
    # Strong signal for common metric variants.
    if {"ebitda","adjusted ebitda"} <= {ma,mb} or ("adjusted" in ma) != ("adjusted" in mb) and "ebitda" in ma+mb:
        return "reconcilable_context",f"Metric labels differ ({a.get('metric_label')} vs {b.get('metric_label')}), so the values are not the same defined metric.",0.82
    return "unrelated","The candidate facts do not have sufficiently aligned metric/entity/period semantics.",0.45

def ollama_reconcile(a,b,base_url=None,model=None):
    base_url=base_url or os.getenv("OLLAMA_BASE_URL","http://localhost:11434")
    model=model or os.getenv("OLLAMA_MODEL","llama3.1:8b")
    payload={"model":model,"prompt":_prompt(a,b),"stream":False,"format":"json",
             "options":{"temperature":0}}
    try:
        r=requests.post(base_url.rstrip("/")+"/api/generate",json=payload,timeout=120)
        r.raise_for_status()
        data=r.json()
        out=json.loads(data.get("response","{}"))
        if out.get("relation_type") not in RELATIONS: raise ValueError("bad relation")
        out["confidence"]=float(out.get("confidence",0.5))
        return out
    except Exception:
        typ,exp,conf=heuristic_reconcile(a,b)
        return {"relation_type":typ,"explanation":exp,"confidence":conf}
