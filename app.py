import os, tempfile, pathlib
import streamlit as st
from ingest import ingest_pdf
from extract import extract_from_chunks
from store import Store
from match import Matcher
from reconcile import ollama_reconcile

st.set_page_config(page_title="Fact Knowledge Layer",layout="wide")
st.title("Fact Knowledge Layer")
st.caption("Grounded extraction → normalization → semantic matching → evidence-based reconciliation")

store=Store()
if "processed" not in st.session_state: st.session_state.processed=False

with st.sidebar:
    st.header("Pipeline")
    use_llm=st.checkbox("Use Ollama for reconciliation", value=True)
    threshold=st.slider("Match cosine threshold",0.15,0.90,0.38,0.01)
    st.info("Text-layer PDFs only. Scanned PDFs are reported as having no extractable text.")

uploads=st.file_uploader("Upload one or more PDFs",type=["pdf"],accept_multiple_files=True)

if st.button("Process PDFs",type="primary",disabled=not uploads):
    progress=st.progress(0)
    total=len(uploads)
    for i,up in enumerate(uploads):
        with tempfile.NamedTemporaryFile(suffix=".pdf",delete=False) as tmp:
            tmp.write(up.getvalue()); path=tmp.name
        try:
            doc_id,pages,chunks,has_text=ingest_pdf(path)
            store.add_document(doc_id,up.name,pathlib.Path(up.name).stem,pages)
            if not has_text:
                st.warning(f"{up.name}: no text layer detected; skipped (OCR is not implemented).")
                continue
            facts=extract_from_chunks(chunks)
            ids=store.add_facts(facts)
            st.success(f"{up.name}: {pages} pages → {len(facts)} candidate facts")
        finally:
            os.unlink(path)
        progress.progress((i+1)/total)
    st.session_state.processed=True

facts=store.get_facts()
if facts:
    st.divider()
    tab1,tab2,tab3=st.tabs(["Facts","Relations","Review queue"])
    with tab1:
        df=store.facts_df()
        st.dataframe(df[["fact_id","filename","page_no","metric_label","entity","value_numeric","unit","period_label","confidence","needs_review","raw_text"]],use_container_width=True)
        fid=st.number_input("Fact ID for detail",min_value=1,max_value=max(1,int(df.fact_id.max())),value=1,step=1)
        row=df[df.fact_id==fid]
        if not row.empty:
            r=row.iloc[0]
            st.markdown(f"### Source: {r['filename']} — page {int(r['page_no'])}")
            st.code(str(r["raw_text"]))
            st.write("**Context**")
            st.write(r["context_text"])
    with tab2:
        if st.button("Find & reconcile candidate pairs"):
            matcher=Matcher(threshold=threshold)
            pairs=matcher.candidates(facts)
            st.write(f"Candidate pairs: {len(pairs)}")
            for (i,j),score in pairs:
                a,b=facts[i],facts[j]
                result=ollama_reconcile(a,b) if use_llm else dict(zip(["relation_type","explanation","confidence"],heuristic_reconcile(a,b)))
                store.add_relation(a["fact_id"],b["fact_id"],result["relation_type"],result["explanation"],result["confidence"],
                                   "heuristic_match+ollama" if use_llm else "heuristic_match")
            st.rerun()
        rdf=store.relations_df()
        if rdf.empty: st.info("No relations yet. Run candidate reconciliation.")
        else:
            for typ in ["corroborates","contradicts","reconcilable_context","unrelated"]:
                sub=rdf[rdf.relation_type==typ]
                st.subheader(f"{typ} ({len(sub)})")
                for _,r in sub.iterrows():
                    with st.expander(f"#{int(r.relation_id)} | {r.doc_a} p.{int(r.page_a)} ↔ {r.doc_b} p.{int(r.page_b)}"):
                        c1,c2=st.columns(2)
                        c1.write(f"**A:** {r.raw_a}")
                        c2.write(f"**B:** {r.raw_b}")
                        st.write(r.explanation)
                        st.caption(f"confidence={r.confidence:.2f} · {r.created_by}")
    with tab3:
        review=store.facts_df()
        review=review[review.needs_review==1]
        st.metric("Low-confidence facts",len(review))
        st.dataframe(review[["fact_id","filename","page_no","metric_label","value_numeric","unit","raw_text","confidence"]],use_container_width=True)
else:
    st.info("Upload PDFs to begin. The system has no filename-specific assumptions.")
