"""
DPDP / GDPR Compliance Impact Agent
Single-file Streamlit app — no separate FastAPI server needed.
Deploy directly to Streamlit Community Cloud.
"""

from __future__ import annotations

# ── stdlib ──────────────────────────────────────────────────────────────────
import json
import os
import re
import sys
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Literal

# ── third-party ──────────────────────────────────────────────────────────────
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Load .env for local development (no-op on Streamlit Cloud)
load_dotenv(Path(__file__).parent / ".env")

# ════════════════════════════════════════════════════════════════════════════
# 0.  CONFIG  (reads from Streamlit secrets or env vars)
# ════════════════════════════════════════════════════════════════════════════

def _get_secret(key: str, default: str = "") -> str:
    """Read from st.secrets first, then os.environ."""
    try:
        # Streamlit secrets: flat key or nested under [llm]
        return st.secrets.get(key) or st.secrets.get("llm", {}).get(key) or os.environ.get(key, default)
    except Exception:
        return os.environ.get(key, default)


class _Cfg:
    groq_api_key: str        = ""
    groq_base_url: str       = "https://api.groq.com/openai/v1"
    groq_model: str          = "llama-3.3-70b-versatile"
    openai_api_key: str      = ""
    openai_model: str        = "gpt-4o"
    llm_provider: str        = "auto"          # auto | groq | openai
    embedding_provider: str  = "auto"          # auto | local | openai
    embedding_model: str     = "text-embedding-3-small"
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size: int          = 800
    chunk_overlap: int       = 120
    retrieval_k: int         = 5
    max_reg_chunks: int      = 24
    max_upload_bytes: int    = 15 * 1024 * 1024


def _load_cfg() -> _Cfg:
    c = _Cfg()
    c.groq_api_key       = _get_secret("GROQ_API_KEY")
    c.groq_model         = _get_secret("GROQ_MODEL", c.groq_model)
    c.openai_api_key     = _get_secret("OPENAI_API_KEY")
    c.openai_model       = _get_secret("OPENAI_MODEL", c.openai_model)
    c.llm_provider       = _get_secret("LLM_PROVIDER", c.llm_provider)
    c.embedding_provider = _get_secret("EMBEDDING_PROVIDER", c.embedding_provider)
    c.embedding_model    = _get_secret("EMBEDDING_MODEL", c.embedding_model)
    c.local_embedding_model = _get_secret("LOCAL_EMBEDDING_MODEL", c.local_embedding_model)
    return c


CFG = _load_cfg()


def _resolved_llm() -> Literal["groq", "openai"]:
    p = CFG.llm_provider
    if p == "groq":
        if not CFG.groq_api_key.strip():
            raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is empty.")
        return "groq"
    if p == "openai":
        if not CFG.openai_api_key.strip():
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is empty.")
        return "openai"
    if CFG.groq_api_key.strip():
        return "groq"
    if CFG.openai_api_key.strip():
        return "openai"
    raise RuntimeError("Set GROQ_API_KEY (or OPENAI_API_KEY) in Streamlit secrets.")


def _resolved_embed() -> Literal["local", "openai"]:
    p = CFG.embedding_provider
    if p == "local":
        return "local"
    if p == "openai":
        if not CFG.openai_api_key.strip():
            raise RuntimeError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY.")
        return "openai"
    # auto
    return "openai" if CFG.openai_api_key.strip() else "local"


# ════════════════════════════════════════════════════════════════════════════
# 1.  PROMPTS  (inline — no file I/O needed on Streamlit Cloud)
# ════════════════════════════════════════════════════════════════════════════

PROMPT_SUMMARIZE = """You are a senior privacy counsel and regulatory analyst. Summarize the regulation text with precision. Do not invent articles or obligations not supported by the text.

Return a single JSON object with exactly these keys:
- "executive_summary": string, 2-4 sentences for executives
- "obligations": array of strings, concrete obligations (each item one obligation)
- "compliance_requirements": array of strings, measurable or actionable compliance requirements
- "data_subject_rights": array of strings, rights mentioned (empty array if none)
- "security_and_breach": array of strings, security or breach-related duties
- "cross_border_or_transfers": array of strings, transfer / localization rules if any

Use concise legal-technical language. If the source is ambiguous, reflect ambiguity in shorter items rather than guessing specifics."""

PROMPT_COMPARE = """You compare a specific regulation excerpt against retrieved sections of a company privacy policy.

Rules:
- Base conclusions ONLY on the provided regulation excerpt and policy excerpts.
- Classify compliance status as one of: "compliant", "partial", "non-compliant", "unclear"
- gap_type: one of "missing_coverage", "weak_implementation", "contradiction", "ambiguous_clause", "none"
- risk: one of "high", "medium", "low" — use the FULL spectrum; do not default everything to "high".
  - "high": material gap — mandatory obligation absent or contradicted.
  - "medium": partial coverage or weak implementation.
  - "low": minor gaps — largely aligned; small clarification suffices.
- recommendation: 2-4 bullet-level actionable steps.

Return JSON with keys:
- "regulation_excerpt_summary": string (max 1 sentence)
- "compliance_status": string
- "gap": string
- "gap_type": string
- "risk": string
- "recommendation": string
- "policy_evidence": string"""

PROMPT_DEPT = """You map compliance issues to organizational owning teams.

Given a JSON array of issues (issue_index, gap, risk, recommendation), assign departments from this fixed list only:
- "Legal"
- "Security"
- "Backend Engineering"
- "Customer Support"
- "Compliance Teams"

Pick 1-3 departments per issue. Return JSON: { "mappings": [ { "issue_index": number, "departments": string[] } ] }"""


# ════════════════════════════════════════════════════════════════════════════
# 2.  TEXT UTILITIES
# ════════════════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ════════════════════════════════════════════════════════════════════════════
# 3.  EXTRACTION
# ════════════════════════════════════════════════════════════════════════════

def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        parts = [page.get_text("text") for page in doc]
        doc.close()
        return clean_text("\n\n".join(parts))
    if suffix == ".txt":
        raw = path.read_bytes()
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return clean_text(raw.decode(enc))
            except UnicodeDecodeError:
                continue
        return clean_text(raw.decode("utf-8", errors="replace"))
    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        return clean_text("\n\n".join(paras))
    raise ValueError(f"Unsupported file type: {suffix}")


# ════════════════════════════════════════════════════════════════════════════
# 4.  CHUNKING
# ════════════════════════════════════════════════════════════════════════════

def split_text(text: str) -> list[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CFG.chunk_size,
        chunk_overlap=CFG.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return [c.strip() for c in splitter.split_text(text) if c.strip()]


# ════════════════════════════════════════════════════════════════════════════
# 5.  EMBEDDINGS + VECTOR STORE
# ════════════════════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner="Loading embedding model…")
def _get_local_embeddings(model_name: str):
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_embeddings():
    provider = _resolved_embed()
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=CFG.embedding_model, api_key=CFG.openai_api_key)
    return _get_local_embeddings(CFG.local_embedding_model)


def build_faiss_index(chunks: list[str]):
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document as LCDoc
    emb = get_embeddings()
    docs = [LCDoc(page_content=c, metadata={"i": i}) for i, c in enumerate(chunks)]
    return FAISS.from_documents(docs, emb)


def retrieve_context(store, query: str) -> str:
    docs = store.similarity_search(query, k=CFG.retrieval_k)
    return "\n\n".join(f"[Policy chunk {i+1}]\n{d.page_content}" for i, d in enumerate(docs))


# ════════════════════════════════════════════════════════════════════════════
# 6.  LLM
# ════════════════════════════════════════════════════════════════════════════

def _parse_json(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    try:
        out = json.loads(content)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fence:
        try:
            out = json.loads(fence.group(1).strip())
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", content)
    if m:
        try:
            out = json.loads(m.group())
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
    return {}


def chat_json(system: str, user: str, temperature: float = 0.2) -> dict[str, Any]:
    from openai import OpenAI
    provider = _resolved_llm()
    if provider == "groq":
        client = OpenAI(api_key=CFG.groq_api_key, base_url=CFG.groq_base_url)
        model = CFG.groq_model
    else:
        client = OpenAI(api_key=CFG.openai_api_key)
        model = CFG.openai_model

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        resp = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
    except Exception:
        resp = client.chat.completions.create(**kwargs)

    content = resp.choices[0].message.content or "{}"
    parsed = _parse_json(content)
    return parsed if parsed else {"error": "invalid_json", "raw": content[:2000]}


# ════════════════════════════════════════════════════════════════════════════
# 7.  COMPLIANCE ENGINE
# ════════════════════════════════════════════════════════════════════════════

def _readiness_score(findings: list[dict]) -> int:
    score = 100
    penalty = {"high": 15, "medium": 8, "low": 3}
    for f in findings:
        if (str(f.get("compliance_status", "")).lower() == "compliant"
                and str(f.get("gap_type", "")).lower() == "none"):
            continue
        score -= penalty.get(str(f.get("risk", "low")).lower(), 4)
    return max(0, min(100, score))


def _normalize_finding(raw: dict, idx: int) -> dict:
    if raw.get("error") == "invalid_json":
        raw = {
            "compliance_status": "unclear",
            "gap_type": "ambiguous_clause",
            "risk": "medium",
            "gap": "LLM response was not valid JSON for this clause.",
            "recommendation": "Retry analysis or reduce document length.",
            "regulation_excerpt_summary": "",
            "policy_evidence": str(raw.get("raw", ""))[:400],
        }
    risk = str(raw.get("risk", "medium")).lower()
    if risk not in ("high", "medium", "low"):
        risk = "medium"
    status = str(raw.get("compliance_status", "unclear")).lower()
    if status == "compliant" and str(raw.get("gap_type", "")).lower() == "none":
        top = "compliant"
    elif status == "partial":
        top = "partial"
    elif status == "non-compliant":
        top = "non-compliant"
    else:
        top = "partial"
    return {
        "id": str(uuid.uuid4())[:8],
        "chunk_index": idx,
        "status": top,
        "compliance_status": status,
        "gap": raw.get("gap") or "Unable to determine gap.",
        "gap_type": str(raw.get("gap_type", "none")).lower(),
        "risk": risk,
        "recommendation": raw.get("recommendation") or "Review policy language.",
        "regulation_excerpt_summary": raw.get("regulation_excerpt_summary", ""),
        "policy_evidence": raw.get("policy_evidence", ""),
        "departments": [],
    }


def run_analysis(reg_path: Path, pol_path: Path, progress_cb=None) -> dict[str, Any]:
    """Full pipeline: extract → chunk → embed → RAG → LLM → results dict."""

    def _progress(msg: str, pct: float):
        if progress_cb:
            progress_cb(msg, pct)

    _progress("Extracting text from documents…", 0.05)
    reg_text = extract_text(reg_path)
    pol_text = extract_text(pol_path)

    if len(pol_text.strip()) < 50:
        raise ValueError("Company policy text is too short after extraction.")

    _progress("Chunking documents…", 0.10)
    pol_chunks = split_text(pol_text)
    reg_chunks = split_text(reg_text)

    if not reg_chunks:
        raise ValueError("Could not chunk regulation text.")

    if len(reg_chunks) > CFG.max_reg_chunks:
        reg_chunks = reg_chunks[:CFG.max_reg_chunks]

    _progress("Building FAISS vector index…", 0.15)
    vector_store = build_faiss_index(pol_chunks)

    _progress("Summarising regulation with LLM…", 0.20)
    reg_summary = chat_json(PROMPT_SUMMARIZE, f"Regulation text:\n\n{reg_text[:120000]}", temperature=0.2)
    if reg_summary.get("error") == "invalid_json":
        reg_summary = {
            "executive_summary": "Summary unavailable — model returned non-JSON.",
            "obligations": [], "compliance_requirements": [],
            "data_subject_rights": [], "security_and_breach": [],
            "cross_border_or_transfers": [],
        }

    findings: list[dict] = []
    n = len(reg_chunks)
    for idx, chunk in enumerate(reg_chunks):
        pct = 0.25 + 0.60 * (idx / n)
        _progress(f"Analysing regulation chunk {idx + 1}/{n}…", pct)
        ctx = retrieve_context(vector_store, chunk)
        user_msg = (
            f"Regulation excerpt:\n{chunk}\n\n"
            f"Retrieved company policy excerpts:\n{ctx}\n\n"
            "Respond with JSON only per system instructions."
        )
        raw = chat_json(PROMPT_COMPARE, user_msg, temperature=0.15)
        findings.append(_normalize_finding(raw, idx))

    _progress("Mapping findings to departments…", 0.88)
    issues_payload = [
        {"issue_index": i, "gap": f["gap"], "risk": f["risk"], "recommendation": f["recommendation"]}
        for i, f in enumerate(findings)
    ]
    dept_raw = chat_json(PROMPT_DEPT, f"Issues JSON array:\n{json.dumps(issues_payload, ensure_ascii=False)}\n", temperature=0.1)
    allowed = {"Legal", "Security", "Backend Engineering", "Customer Support", "Compliance Teams"}
    for m in (dept_raw.get("mappings") or []):
        try:
            i = int(m.get("issue_index", -1))
            if 0 <= i < len(findings):
                findings[i]["departments"] = [d for d in (m.get("departments") or []) if d in allowed]
        except (TypeError, ValueError):
            continue

    readiness = _readiness_score(findings)
    risk_counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        r = str(f.get("risk", "low")).lower()
        if r in risk_counts:
            risk_counts[r] += 1

    if risk_counts["high"] > 0 or any(str(f.get("compliance_status", "")).lower() == "non-compliant" for f in findings):
        aggregated = "non-compliant"
    elif risk_counts["medium"] > 0:
        aggregated = "partial"
    else:
        aggregated = "compliant"

    _progress("Done.", 1.0)
    return {
        "job_id": str(uuid.uuid4()),
        "regulation_summary": reg_summary,
        "policy_stats": {
            "policy_chunks": len(pol_chunks),
            "regulation_chunks_analyzed": len(reg_chunks),
            "retrieval_k": CFG.retrieval_k,
        },
        "findings": findings,
        "risk_summary": risk_counts,
        "compliance_readiness_score": readiness,
        "aggregated_status": aggregated,
    }


# ════════════════════════════════════════════════════════════════════════════
# 8.  UI HELPERS
# ════════════════════════════════════════════════════════════════════════════

def risk_counts_from_results(results: dict) -> tuple[int, int, int]:
    findings = results.get("findings") or []
    h = m = l = 0
    for f in findings:
        r = str(f.get("risk", "") or "").lower().strip()
        if r == "high":
            h += 1
        elif r == "medium":
            m += 1
        else:
            l += 1
    if findings:
        return h, m, l
    rs = results.get("risk_summary") or {}
    return int(rs.get("high", 0)), int(rs.get("medium", 0)), int(rs.get("low", 0))


def risk_badge(risk: str) -> str:
    r = str(risk).lower()
    colors = {"high": "#c0392b", "medium": "#e67e22", "low": "#27ae60"}
    bg = colors.get(r, "#7f8c8d")
    return f'<span style="background:{bg};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.78rem;font-weight:600;">{r.upper()}</span>'


def load_css() -> None:
    css_path = Path(__file__).parent / "frontend" / "styles" / "custom.css"
    if css_path.is_file():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# 9.  MAIN STREAMLIT APP
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    st.set_page_config(
        page_title="Compliance Impact Agent",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_css()

    st.title("🛡️ Compliance Impact Agent")
    st.caption("DPDP / GDPR · RAG-backed gap analysis · Risk classification · Department routing · Codespire Hackathon 2026")

    # ── session state ────────────────────────────────────────────────────────
    if "results" not in st.session_state:
        st.session_state.results = None

    # ── sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 📂 Upload Documents")

        # API key input (if not set via secrets)
        if not CFG.groq_api_key.strip() and not CFG.openai_api_key.strip():
            st.warning("No API key found in secrets.")
            key_input = st.text_input("Enter GROQ_API_KEY", type="password")
            if key_input:
                CFG.groq_api_key = key_input
        else:
            provider_label = "Groq" if CFG.groq_api_key.strip() else "OpenAI"
            st.success(f"✅ {provider_label} API key loaded")

        reg_file = st.file_uploader("📜 Regulation (PDF / TXT / DOCX)", type=["pdf", "txt", "docx"])
        pol_file = st.file_uploader("🏢 Company Privacy Policy", type=["pdf", "txt", "docx"])

        st.divider()
        run_btn = st.button("🚀 Run Analysis", type="primary", use_container_width=True, disabled=(not reg_file or not pol_file))

        if not reg_file or not pol_file:
            st.caption("Upload both documents to enable analysis.")

        st.divider()
        if st.session_state.results:
            if st.button("🗑️ Clear results", use_container_width=True):
                st.session_state.results = None
                st.rerun()

    # ── run analysis ─────────────────────────────────────────────────────────
    if run_btn and reg_file and pol_file:
        status_box = st.empty()
        progress_bar = st.progress(0)

        def _cb(msg: str, pct: float):
            status_box.info(f"⏳ {msg}")
            progress_bar.progress(min(pct, 1.0))

        try:
            with tempfile.TemporaryDirectory() as tmp:
                reg_path = Path(tmp) / reg_file.name
                pol_path = Path(tmp) / pol_file.name
                reg_path.write_bytes(reg_file.getvalue())
                pol_path.write_bytes(pol_file.getvalue())
                results = run_analysis(reg_path, pol_path, progress_cb=_cb)

            st.session_state.results = results
            status_box.success("✅ Analysis complete!")
            progress_bar.progress(1.0)

        except Exception as exc:
            status_box.error(f"❌ Analysis failed: {exc}")
            progress_bar.empty()
            st.stop()

    # ── results ───────────────────────────────────────────────────────────────
    results = st.session_state.results
    if not results:
        st.info("👈 Upload a regulation and a company policy, then click **Run Analysis**.")
        with st.expander("📋 Sample files available"):
            st.markdown("""
- `data/samples/sample_regulation.txt`
- `data/samples/sample_company_policy.txt`

You can also use the bundled PDFs in the repo root:
- `DPDP_Regulation_Sample.pdf`
- `Incomplete_Company_Privacy_Policy.pdf`
""")
        return

    # ── metrics row ───────────────────────────────────────────────────────────
    score = results.get("compliance_readiness_score", 0)
    agg   = results.get("aggregated_status", "—")
    h_ct, m_ct, l_ct = risk_counts_from_results(results)
    n_findings = len(results.get("findings") or [])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compliance Readiness", f"{score}%")
    c2.metric("Aggregate Posture", str(agg).replace("-", " ").title())
    c3.metric("High-risk Findings", h_ct)
    c4.metric("Medium / Low Findings", f"{m_ct} / {l_ct}")

    st.caption(
        f"Tallied from **{n_findings}** findings · "
        f"High={h_ct} · Medium={m_ct} · Low={l_ct}"
    )

    # ── tabs ──────────────────────────────────────────────────────────────────
    tab_sum, tab_gap, tab_dept, tab_raw = st.tabs(
        ["📋 Regulation Intelligence", "🔍 Gaps & Remediation", "🏢 Department Impact", "📥 Export / JSON"]
    )

    summary  = results.get("regulation_summary") or {}
    findings = results.get("findings") or []

    with tab_sum:
        st.subheader("Executive Narrative")
        st.write(summary.get("executive_summary", "—"))

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Obligations**")
            for o in summary.get("obligations") or []:
                st.markdown(f"- {o}")
        with col_b:
            st.markdown("**Compliance Requirements**")
            for o in summary.get("compliance_requirements") or []:
                st.markdown(f"- {o}")

        st.markdown("**Data Subject Rights**")
        st.write(", ".join(summary.get("data_subject_rights") or []) or "—")

        st.markdown("**Security & Breach**")
        for o in summary.get("security_and_breach") or []:
            st.markdown(f"- {o}")

        st.markdown("**Cross-border / Transfers**")
        for o in summary.get("cross_border_or_transfers") or []:
            st.markdown(f"- {o}")

    with tab_gap:
        st.subheader("Semantic Gap Analysis (RAG)")
        if not findings:
            st.write("No findings.")
        else:
            rows = [
                {
                    "Risk":           f.get("risk"),
                    "Status":         f.get("compliance_status"),
                    "Gap type":       f.get("gap_type"),
                    "Gap":            f.get("gap"),
                    "Recommendation": f.get("recommendation"),
                }
                for f in findings
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.divider()
            for f in findings:
                st.markdown(risk_badge(str(f.get("risk"))), unsafe_allow_html=True)
                st.markdown(f"**Clause focus:** {f.get('regulation_excerpt_summary') or '—'}")
                st.markdown(f"**Gap:** {f.get('gap')}")
                st.markdown(f"**Recommendation:** {f.get('recommendation')}")
                st.markdown(f"**Policy signal:** {f.get('policy_evidence')}")
                st.divider()

    with tab_dept:
        st.subheader("Impacted Departments")
        dept_hits: dict[str, int] = {}
        for f in findings:
            for d in f.get("departments") or []:
                dept_hits[d] = dept_hits.get(d, 0) + 1
        if dept_hits:
            st.bar_chart(pd.Series(dept_hits))
        else:
            st.caption("Department tags appear after analysis completes.")

        st.markdown("**Per-finding ownership hints**")
        for f in findings:
            depts = ", ".join(f.get("departments") or []) or "—"
            st.markdown(f"- ({f.get('risk')}) {depts}")

    with tab_raw:
        st.download_button(
            "⬇️ Download JSON Report",
            data=json.dumps(results, indent=2),
            file_name=f"compliance_report_{results.get('job_id', 'job')}.json",
            mime="application/json",
        )
        st.json(results)


if __name__ == "__main__":
    main()
