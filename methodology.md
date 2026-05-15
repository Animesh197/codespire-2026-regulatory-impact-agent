# Methodology: Retrieval-Augmented Compliance Gap Analysis

This document formalizes the information retrieval design, prompt contracts, scoring semantics, complexity model, and known limitations of the Compliance Impact Agent. It is written for ML engineers and GRC stakeholders who require traceability and reproducibility, not a marketing summary.

---

## 1. Problem Formulation

Given a regulation corpus R and a company policy corpus P, the system approximates:

```
Gap(r_i, P) = LLM( r_i, TopK(r_i, P) )
```

where `r_i` is the i-th regulation chunk and `TopK` is dense retrieval over embedded policy chunks.

The system does not solve legal entailment. It approximates coverage and defensibility of internal policy language against regulatory obligations surfaced in each `r_i`. The distinction is material: a finding of "compliant" means the retrieved policy text contains language that the LLM judges as responsive to the regulation excerpt — not that the organization is legally compliant.

---

## 2. Corpus Construction

### 2.1 Policy Index (Retrieval Corpus)

The policy document is processed as follows:

1. Extract plain text from the uploaded artifact using PyMuPDF (PDF), python-docx (DOCX), or direct byte decoding with encoding fallback (TXT).
2. Normalize whitespace and Unicode via `clean_text()`.
3. Split into overlapping chunks `{p_j}` using `RecursiveCharacterTextSplitter`:
   - Target chunk length: 800 characters
   - Overlap: 120 characters
   - Separator hierarchy: paragraph break, line break, sentence boundary, word boundary, character
4. Embed each chunk `p_j` into a dense vector `v_j` in R^d:
   - Local path: `sentence-transformers/all-MiniLM-L6-v2`, d=384, L2-normalized
   - OpenAI path: `text-embedding-3-small` or configured model, d=1536
5. Build an in-memory FAISS flat index over normalized vectors. Inner-product search on normalized vectors is equivalent to cosine similarity.

Design invariant: only policy text enters the vector index. Regulation text is never indexed. This ensures retrieval answers the question "does our policy contain language relevant to this regulatory obligation?" without cross-contamination.

### 2.2 Regulation Stream (Query Stream)

1. Extract and normalize regulation text using the same pipeline as policy.
2. Split into chunks `{r_i}` using identical splitter hyperparameters for comparability.
3. Apply optional cap: `N' = min(N, max_reg_chunks)` where `max_reg_chunks` defaults to 24. This controls LLM call count and therefore cost and latency.

The cap is applied to the leading chunks. For regulations with a preamble followed by operative clauses, consider pre-processing to remove non-normative text before upload.

---

## 3. Retrieval Specification

For each regulation chunk `r_i`:

1. Embed `r_i` using the same embedding model as the policy index. Embedding model consistency is a hard requirement; mixing models produces meaningless similarity scores.
2. Execute FAISS similarity search to retrieve K nearest policy chunks (default K=5).
3. Pack retrieved chunks into a numbered context block for the LLM prompt.

The retrieval step is a single-stage dense retrieval with no re-ranking. A cross-encoder re-ranker between FAISS candidates and the LLM would improve precision at the cost of additional inference latency. This is noted as a production improvement path.

---

## 4. Prompt Contracts

Three prompt contracts govern all LLM interactions. They are defined as inline string constants in `streamlit_app.py` and versioned with the codebase.

| ID | Constant | Output Schema | Temperature | Role |
|---|---|---|---|---|
| P1 | `PROMPT_SUMMARIZE` | Single JSON object with six thematic arrays | 0.2 | Macro obligations catalog from full regulation text |
| P2 | `PROMPT_COMPARE` | Single JSON object with seven fields per chunk pair | 0.15 | Grounded gap assessment for one regulation chunk against retrieved policy context |
| P3 | `PROMPT_DEPT` | JSON object with `mappings[]` array | 0.1 | RACI-style department assignment across all findings |

**Contract enforcement strategy:**

- Primary: `response_format={"type": "json_object"}` where the provider supports it (Groq, OpenAI).
- Fallback: tolerant JSON extraction in `_parse_json()` — attempts direct parse, then fenced code block extraction, then regex brace matching.
- Degradation: if all extraction attempts fail, the finding is populated with `error: invalid_json` and a truncated raw response. The pipeline continues rather than aborting.

Low temperature values are intentional. Gap analysis requires consistent, grounded outputs. Higher temperatures increase creative hallucination risk, which is the primary failure mode for this task.

---

## 5. Gap Taxonomy

Each finding produced by P2 carries the following fields:

| Field | Type | Values | Interpretation |
|---|---|---|---|
| `compliance_status` | enum | compliant, partial, non-compliant, unclear | LLM's ordinal judgment of policy coverage for this regulation excerpt |
| `gap_type` | enum | missing_coverage, weak_implementation, contradiction, ambiguous_clause, none | Structural classification of the gap |
| `risk` | enum | high, medium, low | Operational and legal exposure heuristic |
| `gap` | string | Free text | Narrative description of the gap or "No material gap detected" |
| `recommendation` | string | Free text | 2-4 actionable remediation steps |
| `regulation_excerpt_summary` | string | Free text | One-sentence summary of the regulation clause |
| `policy_evidence` | string | Free text | Most relevant retrieved policy language, or explicit statement of absence |

Risk calibration guidance in P2 is explicit:
- High: material gap where a mandatory obligation is absent or directly contradicted; severe regulatory exposure if unaddressed.
- Medium: partial coverage; policy mentions the topic but lacks specificity, defined processes, timeframes, or operational controls.
- Low: minor gap; policy intent is clear but wording is ambiguous or a small clarification is needed.

These labels are heuristic classifications produced by a language model. They are not quantitative risk scores and should not be treated as such in regulatory filings.

---

## 6. Aggregation Semantics

### 6.1 Risk Histogram

```
count(t) = |{ f in F : risk(f) = t }|,  t in {high, medium, low}
```

where F is the complete findings list.

### 6.2 Aggregated Posture

The aggregated status is computed as a conservative lattice to bias toward false positives (safer for compliance tooling than false negatives):

1. If any finding has `compliance_status = non-compliant` OR `count(high) > 0` → `non-compliant`
2. Else if `count(medium) > 0` → `partial`
3. Else → `compliant`

### 6.3 Compliance Readiness Score

Let F' be the subset of findings where the finding is not simultaneously `compliant` and `gap_type = none`. Define penalties:

```
pi(high) = 15
pi(medium) = 8
pi(low) = 3
```

```
score = max(0, 100 - sum_{f in F'} pi(risk(f)))
```

The score is bounded to [0, 100]. It is a demo KPI designed to give a single-number summary for presentation purposes. It is not derived from any ISO standard, NIST framework, or actuarial model. Organizations should not use this score as a compliance certification metric.

---

## 7. Complexity and Cost Model

Let:
- N' = number of regulation chunks analyzed (after cap)
- M = number of policy chunks
- K = retrieval width (default: 5)

**LLM calls per analysis session:**

```
C_LLM = 1 (P1: summarize) + N' (P2: compare, one per reg chunk) + 1 (P3: departments)
      = N' + 2
```

**Embedding calls:**

```
C_emb = M + N'  (policy index build + regulation chunk queries)
```

With default settings (max_reg_chunks=24, K=5), a typical analysis session makes 26 LLM calls. Dominant latency is N' x LLM round-trip time. On Groq with llama-3.3-70b-versatile, each call typically completes in 1-4 seconds, giving a total analysis time of 30-120 seconds depending on document complexity.

**Cost estimation:**
- Groq: ~$0.50-$2.00 per analysis (varies by document size)
- OpenAI GPT-4: ~$2.00-$8.00 per analysis
- Local embeddings: zero API cost

---

## 8. Evaluation Framework

For hackathon judging or internal quality assurance, the following metrics are recommended:

| Metric | Definition | Measurement Approach |
|---|---|---|
| Citation fidelity | Proportion of findings where `policy_evidence` is semantically related to at least one retrieved chunk | Manual rubric on a sample of 20-30 findings |
| Retrieval precision at K | Proportion of retrieved policy chunks judged relevant to the regulation query by a domain expert | Offline annotation notebook with sampled regulation chunks |
| JSON validity rate | Proportion of LLM calls producing parseable JSON without fallback extraction | Log parser counting `invalid_json` occurrences in results |
| Risk calibration | Agreement between LLM risk labels and expert labels on a held-out clause set | Cohen's kappa on expert-annotated sample |
| End-to-end latency P95 | 95th percentile of total analysis time across multiple runs | Instrumented timing around `run_analysis()` |

Gold labels for compliance gap assessment are expensive to produce. A practical starting point is expert spot-checks on 10-20 clause pairs covering each gap_type category.

---

## 9. Failure Modes and Mitigations

| Failure Mode | Root Cause | Current Behavior | Recommended Mitigation |
|---|---|---|---|
| Retrieval misses relevant policy clause | Terminology mismatch between regulation and policy | Finding shows weak or absent policy_evidence | Query rewriting with synonym expansion; increase K |
| LLM over-claims compliance | Insufficient grounding; model fills gaps with plausible language | False negatives in gap detection | Require explicit "no evidence found" utterance in prompt; lower temperature |
| All findings rated high risk | Model ignores risk calibration guidance | Inflated readiness score penalty | Strengthen risk calibration examples in P2; use few-shot prompting |
| PDF text extraction failure | Scanned PDF without embedded text layer | Empty or near-empty extracted text; validation error | Add OCR preprocessing stage (Tesseract or cloud OCR) |
| Regulation truncation | Document exceeds chunk budget | Later clauses not analyzed | Raise max_reg_chunks with awareness of cost increase; pre-filter non-normative sections |
| JSON parse failure cascade | Model returns markdown or prose instead of JSON | Degraded finding with error marker | Upgrade to a model with stronger instruction following; add retry with explicit JSON reminder |

---

## 10. Reproducibility Checklist

To reproduce a specific analysis result:

- Record the `LLM_PROVIDER`, model name, and embedding provider from the session configuration.
- Retain the exported JSON report, which includes `policy_stats` (chunk counts, K, analyzed N').
- Note the Git commit SHA of `streamlit_app.py` to recover the exact prompt text used.
- Pin dependency versions: reinstall from `requirements.txt` with the same package versions.
- Note that exact reproduction is not guaranteed due to LLM non-determinism at temperature > 0.

---

## 11. Compliance and Ethics Disclaimer

Outputs from this system are decision-support artifacts only. They are produced by a language model operating on retrieved text and are subject to hallucination, retrieval gaps, and prompt sensitivity. Final legal positions require review by qualified privacy counsel and organizational policy owners. Readiness scores must not be submitted as evidence of regulatory compliance to any authority.

---

## 12. Code Reference

| Component | Location |
|---|---|
| Full pipeline orchestration | `run_analysis()` in `streamlit_app.py` |
| LLM client and JSON parsing | `chat_json()`, `_parse_json()` in `streamlit_app.py` |
| Retrieval | `retrieve_context()`, `build_faiss_index()` in `streamlit_app.py` |
| Embedding selection | `get_embeddings()`, `_resolved_embed()` in `streamlit_app.py` |
| Configuration | `_Cfg`, `_load_cfg()`, `_resolved_llm()` in `streamlit_app.py` |
| Prompt contracts | `PROMPT_SUMMARIZE`, `PROMPT_COMPARE`, `PROMPT_DEPT` in `streamlit_app.py` |
