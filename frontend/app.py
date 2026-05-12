"""Streamlit dashboard — DPDP/GDPR Compliance Impact Agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx
import pandas as pd
import streamlit as st

from frontend.services.api_client import (
    analyze_job,
    check_health,
    format_api_error,
    get_results,
    upload_documents,
)

def load_css() -> None:
    css_path = Path(__file__).parent / "styles" / "custom.css"
    if css_path.is_file():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def risk_counts_from_results(results: dict) -> tuple[int, int, int]:
    """Prefer tally from `findings[]` so metrics match rows (source of truth)."""
    findings = results.get("findings") or []
    h = m = l = 0
    for f in findings:
        r = str(f.get("risk", "") or "").lower().strip()
        if r == "high":
            h += 1
        elif r == "medium":
            m += 1
        elif r == "low":
            l += 1
        else:
            m += 1
    if findings:
        return h, m, l
    rs = results.get("risk_summary") or {}
    return (
        int(rs.get("high", 0) or 0),
        int(rs.get("medium", 0) or 0),
        int(rs.get("low", 0) or 0),
    )


def risk_pill_class(risk: str) -> str:
    r = str(risk).lower()
    if r == "high":
        return "pill-high"
    if r == "medium":
        return "pill-medium"
    return "pill-low"


def main() -> None:
    st.set_page_config(
        page_title="Compliance Impact Agent",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_css()

    st.title("Compliance Impact Agent")
    st.caption(
        "DPDP / GDPR · RAG-backed gap analysis · Risk classification · Department routing · Codespire Hackathon 2026"
    )

    if "job_id" not in st.session_state:
        st.session_state.job_id = None
    if "last_results" not in st.session_state:
        st.session_state.last_results = None

    with st.sidebar:
        st.markdown("#### Control plane")
        api_base = st.text_input("API base URL", value="http://127.0.0.1:8000")
        healthy = check_health(api_base)
        st.write("API status:", "🟢 reachable" if healthy else "🔴 unreachable")

        reg_file = st.file_uploader("Regulation (PDF / TXT / DOCX)", type=["pdf", "txt", "docx"])
        pol_file = st.file_uploader("Company privacy policy", type=["pdf", "txt", "docx"])

        col_a, col_b = st.columns(2)
        with col_a:
            upload_btn = st.button("Upload", type="primary", use_container_width=True)
        with col_b:
            analyze_btn = st.button("Analyze", use_container_width=True)

        if upload_btn:
            if not reg_file or not pol_file:
                st.error("Upload both documents first.")
            else:
                tmp = _ROOT / "data" / "_streamlit_tmp"
                tmp.mkdir(parents=True, exist_ok=True)
                reg_path = tmp / reg_file.name
                pol_path = tmp / pol_file.name
                reg_path.write_bytes(reg_file.getvalue())
                pol_path.write_bytes(pol_file.getvalue())
                try:
                    up = upload_documents(api_base, reg_path, pol_path)
                    st.session_state.job_id = up["job_id"]
                    st.success(f"Stored job `{st.session_state.job_id}`")
                except httpx.HTTPError as e:
                    st.error(f"Upload failed: {format_api_error(e)}")

        if analyze_btn:
            jid = st.session_state.job_id
            if not jid:
                st.error("Upload documents first to obtain a job id.")
            else:
                with st.spinner("Running extraction, embeddings, RAG comparison, and synthesis…"):
                    try:
                        resp = analyze_job(api_base, jid)
                        st.session_state.last_results = resp.get("results") or resp
                        st.success("Analysis complete.")
                    except httpx.HTTPError as e:
                        st.error(f"Analyze failed: {format_api_error(e)}")

        st.divider()
        st.caption("Load cached results")
        manual_id = st.text_input("Job ID", value=st.session_state.job_id or "")
        if st.button("Fetch results"):
            if manual_id.strip():
                try:
                    st.session_state.last_results = get_results(api_base, manual_id.strip())
                    st.session_state.job_id = manual_id.strip()
                except httpx.HTTPError as e:
                    st.error(f"Fetch failed: {format_api_error(e)}")

    results = st.session_state.last_results
    if not results:
        st.info("Upload regulations and policy, then run **Analyze** — or fetch results by job id.")
        return

    score = results.get("compliance_readiness_score", 0)
    agg = results.get("aggregated_status", "—")
    n_findings = len(results.get("findings") or [])
    h_ct, m_ct, l_ct = risk_counts_from_results(results)

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Compliance readiness", f"{score}%")
    with m2:
        st.metric("Aggregate posture", str(agg).replace("-", " ").title())
    with m3:
        st.metric("High-risk findings", h_ct)
    with m4:
        st.metric("Medium / Low findings", f"{m_ct} / {l_ct}")

    st.caption(
        f"Counts are tallied from each finding’s **risk** field (**{n_findings}** rows). "
        f"**High={h_ct}, Medium={m_ct}, Low={l_ct}**. "
        "If Medium and Low stay 0, the model judged every slice as **high** severity for your inputs—not a UI bug. "
        "Re-run after prompt tuning, or use documents with clearer partial coverage to see medium/low."
    )

    tab_sum, tab_gap, tab_dept, tab_raw = st.tabs(
        ["Regulation intelligence", "Gaps & remediation", "Department impact", "Export / JSON"]
    )

    summary = results.get("regulation_summary") or {}
    with tab_sum:
        st.subheader("Executive narrative")
        st.write(summary.get("executive_summary", "—"))

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Obligations**")
            for o in summary.get("obligations") or []:
                st.markdown(f"- {o}")
        with c2:
            st.markdown("**Compliance requirements**")
            for o in summary.get("compliance_requirements") or []:
                st.markdown(f"- {o}")

        st.markdown("**Data subject rights**")
        st.write(", ".join(summary.get("data_subject_rights") or []) or "—")

        st.markdown("**Security & breach**")
        for o in summary.get("security_and_breach") or []:
            st.markdown(f"- {o}")

        st.markdown("**Cross-border / transfers**")
        for o in summary.get("cross_border_or_transfers") or []:
            st.markdown(f"- {o}")

    findings = results.get("findings") or []
    with tab_gap:
        st.subheader("Semantic gap analysis (RAG)")
        if not findings:
            st.write("No findings.")
        else:
            rows = []
            for f in findings:
                rows.append(
                    {
                        "Risk": f.get("risk"),
                        "Status": f.get("compliance_status"),
                        "Gap type": f.get("gap_type"),
                        "Gap": f.get("gap"),
                        "Recommendation": f.get("recommendation"),
                    }
                )
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            for i, f in enumerate(findings):
                cls = risk_pill_class(str(f.get("risk")))
                st.markdown(
                    f'<span class="{cls}">{str(f.get("risk")).upper()} risk</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**Clause focus:** {f.get('regulation_excerpt_summary') or '—'}")
                st.markdown(f"**Gap:** {f.get('gap')}")
                st.markdown(f"**Recommendation:** {f.get('recommendation')}")
                st.markdown(f"**Policy signal:** {f.get('policy_evidence')}")
                st.divider()

    with tab_dept:
        st.subheader("Impacted departments")
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
            "Download JSON report",
            data=json.dumps(results, indent=2),
            file_name=f"compliance_report_{results.get('job_id', 'job')}.json",
            mime="application/json",
        )
        st.json(results)


if __name__ == "__main__":
    main()
