import sys, os
from ingest import ingest_pdf
from extract import extract_from_chunks
from match import Matcher
from reconcile import ollama_reconcile

def main(paths):
    all_facts=[]
    for path in paths:
        doc_id,pages,chunks,has_text=ingest_pdf(path)
        if not has_text:
            print(f"[SKIP] {path}: no text layer")
            continue
        facts=extract_from_chunks(chunks)
        for f in facts:
            f.source_doc=os.path.basename(path)
        all_facts.extend([f.__dict__ for f in facts])
        print(f"[OK] {path}: {pages} pages, {len(facts)} facts")
    if not all_facts: return
    matcher=Matcher()
    pairs=matcher.candidates(all_facts)
    print(f"\nCandidate pairs: {len(pairs)}")
    shown={"corroborates":0,"contradicts":0,"reconcilable_context":0,"unrelated":0}
    for (i,j),score in pairs:
        result=ollama_reconcile(all_facts[i],all_facts[j])
        typ=result["relation_type"]; shown[typ]=shown.get(typ,0)+1
        print(f"\n[{typ.upper()}] match={score:.2f} conf={result['confidence']:.2f}")
        print(f"A: {all_facts[i]['source_doc']} p.{all_facts[i]['page_no']} :: {all_facts[i]['raw_text']}")
        print(f"B: {all_facts[j]['source_doc']} p.{all_facts[j]['page_no']} :: {all_facts[j]['raw_text']}")
        print("Why:",result["explanation"])
    print("\nSummary:",shown)

if __name__=="__main__":
    if len(sys.argv)<2:
        print("Usage: python run_demo.py report1.pdf [report2.pdf ...]")
        raise SystemExit(2)
    main(sys.argv[1:])
