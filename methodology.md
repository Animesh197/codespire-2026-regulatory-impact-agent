# Methodology — Advanced RAG & governance analytics

This document formalizes the **information retrieval setup**, **prompt contracts**, **risk semantics**, and **evaluation stance** for the Compliance Impact Agent. It is written for reviewers who care about **traceability** and **limitations**, not buzzwords.

---

## 1. Objective function (informal)

Given regulation corpus \(R\) and policy corpus \(P\), approximate:

\[
\text{Gap}(r_i, P) \approx \text{LLM}\bigl(r_i,\; \text{TopK}(r_i, P)\bigr)
\]

where \(r_i\) is the \(i\)-th regulation chunk and \(\text{TopK}\) is dense retrieval over embedded policy chunks.

We **do not** solve legal entailment; we approximate **coverage** and **defensibility** of internal policy language against regulatory clauses surfaced in \(r_i\).

---

## 2. Corpus construction

### 2.1 Policy index (retrieval corpus)

1. Extract plain text \(P_{\text{raw}}\).
2. Split into chunks \(\{p_j\}_{j=1}^{M}\) with RecursiveCharacterTextSplitter:
   - Target length \(L \approx 800\) characters.
   - Overlap \(\Delta \approx 120\) characters.
3. Embed each \(p_j\) → vector \(v_j \in \mathbb{R}^d\) (MiniLM dimension \(d{=}384\) or OpenAI model-dependent \(d\)).
4. Build FAISS inner-product index on **normalized** vectors (when using local embeddings with `normalize_embeddings=True`).

**Design invariant:** retrieval operates **only** on policy text—regulation text never enters the vector index. This avoids cross-contamination and mirrors “Does our policy mention anything relevant?” queries.

### 2.2 Regulation stream (query stream)

1. Extract \(R_{\text{raw}}\), split into \(\{r_i\}_{i=1}^{N}\) with same splitter hyperparameters for comparability.
2. Optional cap \(N' = \min(N, N_{\max})\) where \(N_{\max}\) is `max_regulation_chunks_for_compare` — controls cost/latency.

---

## 3. Retrieval specification

For each regulation chunk \(r_i\):

1. **Query embedding**: embed \(r_i\) with the **same** embedding model as policy chunks.
2. **Neighbor search**: retrieve \(K\) policy chunks (default \(K{=}5\)) via FAISS similarity search.
3. **Context packing**: concatenate retrieved chunks with lightweight boundaries for the LLM (see `backend/services/rag.py`).

**Why top-\(K\) not re-ranking?** Hackathon scope; cross-encoder reranking would sit between FAISS hits and LLM for higher precision.

---

## 4. Prompt taxonomy (contracts)

| ID | File | Output schema | Temperature (typical) | Role |
|----|------|----------------|----------------------|------|
| **P1** | `summarize_regulation.txt` | Single JSON object with thematic arrays | Low (~0.2) | Macro obligations catalog |
| **P2** | `compare_gap.txt` | Single JSON object per chunk pair evaluation | Low (~0.15) | Grounded gap card |
| **P3** | `department_mapping.txt` | JSON with `mappings[]` | Low (~0.1) | RACI-style routing |

**Contract enforcement:**

- Primary path: `response_format=json_object` where the provider supports it.
- Fallback: tolerant JSON extraction (`backend/services/llm.py`) + structured degradation in `compliance_engine.py`.

---

## 5. Gap taxonomy (encoded in P2)

The LLM labels each slice with:

| Field | Interpretation |
|-------|----------------|
| `compliance_status` | Ordinal perception: compliant / partial / non-compliant / unclear |
| `gap_type` | missing_coverage · weak_implementation · contradiction · ambiguous_clause · none |
| `risk` | high · medium · low — **operational/legal exposure heuristic**, not quantitative VaR |
| `policy_evidence` | Quote or honest statement of weak retrieval |

These labels feed dashboards and CSV/JSON export—they are **not** statutory classifications.

---

## 6. Aggregation semantics

### 6.1 Risk histogram

\[
\text{count}(t) = \bigl|\{ f \in \mathcal{F} : \text{risk}(f)=t \}\bigr|, \quad t \in \{\text{high, medium, low}\}
\]

where \(\mathcal{F}\) is the findings list.

### 6.2 Aggregated posture (`aggregated_status`)

Defined in code as a **conservative** lattice:

1. If \(\exists f\) with `compliance_status = non-compliant` **or** \(\text{count}(\text{high}) > 0\) → **`non-compliant`**.
2. Else if \(\text{count}(\text{medium}) > 0\) → **`partial`**.
3. Else → **`compliant`**.

This biases toward **false positives** on posture (safer for demos than false negatives).

### 6.3 Readiness score (heuristic)

Let \(\mathcal{F}' \subseteq \mathcal{F}\) be findings where **not** (`compliant` ∧ `gap_type = none`). Define penalties \( \pi(\text{high})=15,\ \pi(\text{medium})=8,\ \pi(\text{low})=3 \).

\[
\text{score} = \max\left(0,\ 100 - \sum_{f \in \mathcal{F}'} \pi(\text{risk}(f))\right)
\]

Bounded to \([0,100]\). This is a **demo KPI**, not an ISO metric.

---

## 7. Complexity & cost model (analysis pass)

Let:

- \(N'\) = regulation chunks analyzed (after cap).
- \(K\) = retrieval width.

**Approximate LLM calls:**

\[
C_{\text{LLM}} \approx 1 \ (\text{P1}) + N' \ (\text{P2}) + 1 \ (\text{P3})
\]

**Approximate embedding calls:**

\[
C_{\text{emb}} \approx M + N \quad (\text{policy + regulation chunks})
\]

Dominant latency term is usually **\(N' \times\) LLM round-trip**.

---

## 8. Evaluation framework (recommended)

For hackathon judging or internal QA, track:

| Metric | Definition | Tooling hint |
|--------|--------------|----------------|
| **Citation fidelity** | % findings where `policy_evidence` is substring-related to retrieved chunk | Manual rubric on sample |
| **Retrieval precision@K** | Manual relevance labels on policy hits for sampled \(r_i\) | Offline notebook |
| **JSON validity rate** | % calls producing parseable JSON without fallback | Log parser |
| **Latency P95** | End-to-end `/analyze` | Wireshark / server timestamps |

Gold labels for compliance are expensive—start with **expert spot checks** on 10–20 clause pairs.

---

## 9. Failure modes & mitigations

| Failure | Cause | Mitigation |
|---------|-------|------------|
| Retrieval misses obligation | Policy uses different terminology | Synonym expansion query rewrite; bigger \(K\) |
| LLM over-claims compliance | Weak prompt grounding | Lower temperature; require “no evidence” utterance |
| PDF extraction drops text | Scanned PDF without OCR | Add OCR stage (not in MVP) |
| Long regulation truncation | Chunk budget | Raise \(N_{\max}\) with cost awareness |

---

## 10. Compliance & ethics disclaimer

Outputs are **decision support** only. Final legal positions require qualified counsel and organizational policy owners. Do not use readiness scores as regulatory filings.

---

## 11. Reproducibility checklist

- [ ] `.env` documents `LLM_PROVIDER`, `GROQ_MODEL` / `OPENAI_MODEL`, embedding provider.
- [ ] Saved JSON includes `policy_stats` (chunks, \(K\), analyzed \(N'\)).
- [ ] Prompt files pinned to Git commit SHA used for demo.
- [ ] Dependency lock: reinstall from `requirements.txt` with same versions where possible.

---

## 12. References (repo paths)

| Artifact | Path |
|----------|------|
| Orchestration | `backend/services/compliance_engine.py` |
| LLM client | `backend/services/llm.py` |
| Retrieval | `backend/services/rag.py`, `vector_store.py` |
| Config | `backend/utils/config.py` |
| Prompts | `backend/prompts/*.txt` |
