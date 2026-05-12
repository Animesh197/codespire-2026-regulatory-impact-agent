from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from backend.prompts import load_prompt
from backend.services.chunking import split_documents
from backend.services.extraction import extract_text
from backend.services.llm import chat_json
from backend.services.rag import retrieve_policy_context
from backend.services.vector_store import build_faiss_index
from backend.utils.config import settings


def _readiness_score(findings: list[dict[str, Any]]) -> int:
    score = 100
    penalty = {"high": 15, "medium": 8, "low": 3}
    for f in findings:
        if (
            str(f.get("compliance_status", "")).lower() == "compliant"
            and str(f.get("gap_type", "")).lower() == "none"
        ):
            continue
        r = str(f.get("risk", "low")).lower()
        score -= penalty.get(r, 4)
    return max(0, min(100, score))


def _normalize_compare(raw: dict[str, Any], chunk_idx: int) -> dict[str, Any]:
    if raw.get("error") == "invalid_json":
        raw = {
            "compliance_status": "unclear",
            "gap_type": "ambiguous_clause",
            "risk": "medium",
            "gap": "LLM response was not valid JSON for this clause. Try again or reduce regulation length.",
            "recommendation": "Retry analysis; if it persists, lower MAX_REGULATION_CHUNKS_FOR_COMPARE or change model.",
            "regulation_excerpt_summary": "",
            "policy_evidence": str(raw.get("raw", ""))[:400],
        }
    status = str(raw.get("compliance_status", "unclear")).lower()
    gap_type = str(raw.get("gap_type", "none")).lower()
    risk = str(raw.get("risk", "medium")).lower()
    if risk not in ("high", "medium", "low"):
        risk = "medium"
    gap = raw.get("gap") or "Unable to determine gap from retrieved context."
    rec = raw.get("recommendation") or "Review policy language and operational controls for this obligation."
    if status == "compliant" and gap_type == "none":
        top_status = "compliant"
    elif status == "partial":
        top_status = "partial"
    elif status == "non-compliant":
        top_status = "non-compliant"
    else:
        top_status = "partial"
    return {
        "id": str(uuid.uuid4())[:8],
        "chunk_index": chunk_idx,
        "status": top_status,
        "compliance_status": status,
        "gap": gap,
        "gap_type": gap_type,
        "risk": risk,
        "recommendation": rec,
        "regulation_excerpt_summary": raw.get("regulation_excerpt_summary", ""),
        "policy_evidence": raw.get("policy_evidence", ""),
        "departments": [],
    }


def run_compliance_analysis(
    regulation_path: Path,
    policy_path: Path,
) -> dict[str, Any]:
    regulation_text = extract_text(regulation_path)
    policy_text = extract_text(policy_path)

    if len(policy_text.strip()) < 50:
        raise ValueError("Company policy text is too short after extraction.")

    policy_chunks = split_documents(policy_text)
    reg_chunks = split_documents(regulation_text)

    if not reg_chunks:
        raise ValueError("Could not chunk regulation text.")

    max_c = settings.max_regulation_chunks_for_compare
    if len(reg_chunks) > max_c:
        reg_chunks = reg_chunks[:max_c]

    vector_store = build_faiss_index(policy_chunks)

    summarize_system = load_prompt("summarize_regulation")
    regulation_summary = chat_json(
        summarize_system,
        f"Regulation text:\n\n{regulation_text[:120000]}",
        temperature=0.2,
    )
    if isinstance(regulation_summary, dict) and regulation_summary.get("error") == "invalid_json":
        regulation_summary = {
            "executive_summary": "Summary unavailable (model returned non-JSON). Per-clause analysis below still applies.",
            "obligations": [],
            "compliance_requirements": [],
            "data_subject_rights": [],
            "security_and_breach": [],
            "cross_border_or_transfers": [],
        }

    compare_system = load_prompt("compare_gap")
    findings: list[dict[str, Any]] = []

    for idx, reg_chunk in enumerate(reg_chunks):
        policy_ctx = retrieve_policy_context(vector_store, reg_chunk, k=settings.retrieval_k)
        user_msg = (
            f"Regulation excerpt:\n{reg_chunk}\n\n"
            f"Retrieved company policy excerpts:\n{policy_ctx}\n\n"
            "Respond with JSON only per system instructions."
        )
        raw = chat_json(compare_system, user_msg, temperature=0.15)
        findings.append(_normalize_compare(raw, idx))

    issues_payload = [
        {
            "issue_index": i,
            "gap": f["gap"],
            "risk": f["risk"],
            "recommendation": f["recommendation"],
        }
        for i, f in enumerate(findings)
    ]

    dept_system = load_prompt("department_mapping")
    dept_user = f"Issues JSON array:\n{json.dumps(issues_payload, ensure_ascii=False)}\n"
    dept_raw = chat_json(
        dept_system,
        dept_user,
        temperature=0.1,
    )
    if isinstance(dept_raw, dict) and dept_raw.get("error") == "invalid_json":
        dept_raw = {}
    mappings = dept_raw.get("mappings") or []

    for m in mappings:
        try:
            i = int(m.get("issue_index", -1))
            depts = m.get("departments") or []
            if 0 <= i < len(findings):
                findings[i]["departments"] = depts
        except (TypeError, ValueError):
            continue

    allowed = {
        "Legal",
        "Security",
        "Backend Engineering",
        "Customer Support",
        "Compliance Teams",
    }
    for f in findings:
        f["departments"] = [d for d in f["departments"] if d in allowed]

    readiness = _readiness_score(findings)

    risk_counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        r = str(f.get("risk", "low")).lower()
        if r in risk_counts:
            risk_counts[r] += 1

    if risk_counts["high"] > 0 or any(
        str(f.get("compliance_status", "")).lower() == "non-compliant" for f in findings
    ):
        aggregated = "non-compliant"
    elif risk_counts["medium"] > 0:
        aggregated = "partial"
    else:
        aggregated = "compliant"

    return {
        "regulation_summary": regulation_summary,
        "policy_stats": {
            "policy_chunks": len(policy_chunks),
            "regulation_chunks_analyzed": len(reg_chunks),
            "retrieval_k": settings.retrieval_k,
        },
        "findings": findings,
        "risk_summary": risk_counts,
        "compliance_readiness_score": readiness,
        "aggregated_status": aggregated,
    }
