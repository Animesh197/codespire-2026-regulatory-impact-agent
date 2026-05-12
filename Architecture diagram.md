# Architecture: Compliance Impact Agent

This document provides architectural reasoning for the Compliance Impact Agent: component responsibilities, trust boundaries, data classification, sequence flows, and deployment topologies. It is intended for design reviews and technical due diligence, not operational runbooks (see README.md for those).

---

## 1. Design Goals

| Goal | Mechanism |
|---|---|
| Evidence-linked outputs | Policy chunks retrieved into LLM context for every regulation slice; `policy_evidence` field in each finding |
| Single-process deployment | All logic — extraction, chunking, embeddings, FAISS, RAG, LLM, UI — runs inside one Streamlit process |
| Provider portability | OpenAI SDK with swappable `base_url` covers both Groq and OpenAI without separate client libraries |
| Cost-aware operation | Local sentence-transformers path eliminates embedding API charges; Groq provides low-latency inference at no embedding cost |
| Inspectable artifacts | Full JSON export per session; `policy_stats` block records chunk counts and retrieval parameters for reproducibility |

---

## 2. System Context

The system has one human actor and three external systems:

```
+---------------------+
|  Privacy / GRC      |
|  Analyst            |
+---------------------+
          |
          | browser
          v
+---------------------+
|  Streamlit App      |  <-- single process, single file
|  (streamlit_app.py) |
+---------------------+
     |          |
     v          v
+--------+  +------------------+
| Groq / |  | HuggingFace Hub  |
| OpenAI |  | (first-run model |
| APIs   |  |  download only)  |
+--------+  +------------------+
```

The analyst uploads two documents and receives a structured compliance report. No intermediate HTTP API exists between the UI and the analysis logic. The LLM APIs are the only external network dependencies during normal operation.

---

## 3. Internal Component Decomposition

All components reside in `streamlit_app.py`. The logical layers are:

```
+---------------------------------------------------------------+
|  CONFIGURATION LAYER                                          |
|  _Cfg, _load_cfg(), _resolved_llm(), _resolved_embed()        |
|  Reads from st.secrets (cloud) or os.environ / .env (local)   |
+---------------------------------------------------------------+
|  EXTRACTION LAYER                                             |
|  extract_text()                                               |
|  PyMuPDF (PDF) | python-docx (DOCX) | byte decode (TXT)       |
+---------------------------------------------------------------+
|  CHUNKING LAYER                                               |
|  split_text()                                                 |
|  RecursiveCharacterTextSplitter: 800 chars, 120 overlap       |
+---------------------------------------------------------------+
|  EMBEDDING + INDEX LAYER                                      |
|  get_embeddings() -> HuggingFaceEmbeddings | OpenAIEmbeddings |
|  build_faiss_index(policy_chunks) -> FAISS flat index         |
+---------------------------------------------------------------+
|  RETRIEVAL LAYER                                              |
|  retrieve_context(store, reg_chunk) -> packed context string  |
|  FAISS similarity_search, K=5 default                         |
+---------------------------------------------------------------+
|  LLM LAYER                                                    |
|  chat_json(system, user) -> dict                              |
|  OpenAI SDK; json_object mode with tolerant fallback parsing  |
+---------------------------------------------------------------+
|  COMPLIANCE ENGINE                                            |
|  run_analysis(reg_path, pol_path) -> results dict             |
|  Orchestrates all layers; produces findings[], aggregates     |
+---------------------------------------------------------------+
|  PRESENTATION LAYER                                           |
|  main() Streamlit UI                                          |
|  Sidebar upload, progress bar, metrics row, four result tabs  |
+---------------------------------------------------------------+
```

---

## 4. Analysis Pipeline: Detailed Sequence

```
Analyst uploads regulation + policy
            |
            v
  [1] extract_text(reg_path)
  [2] extract_text(pol_path)
            |
            v
  [3] split_text(pol_text)  -> policy_chunks[]   (M chunks)
  [4] split_text(reg_text)  -> reg_chunks[]       (N chunks, capped at N')
            |
            v
  [5] build_faiss_index(policy_chunks)
      - embed each policy chunk
      - build normalized FAISS flat index
            |
            v
  [6] chat_json(PROMPT_SUMMARIZE, regulation_text[:120000])
      -> regulation_summary dict
            |
            v
  for i in 0..N'-1:
    [7] retrieve_context(store, reg_chunks[i])
        -> top-K policy chunks as context string
    [8] chat_json(PROMPT_COMPARE, reg_chunk + context)
        -> raw finding dict
    [9] _normalize_finding(raw, i)
        -> structured finding with risk, gap_type, compliance_status
            |
            v
  [10] chat_json(PROMPT_DEPT, issues_payload)
       -> department mappings for all findings
            |
            v
  [11] _readiness_score(findings)
  [12] aggregate posture (conservative lattice)
            |
            v
  results dict -> st.session_state -> UI render
```

Total LLM calls: N' + 2 (one summarize, N' compare, one department mapping).

---

## 5. Trust Boundaries and Data Classification

```
+---------------------------+
|  UNTRUSTED INPUT PLANE    |
|  Uploaded PDF/DOCX/TXT    |
|  (arbitrary user content) |
+---------------------------+
            |
            | extract_text() + clean_text()
            v
+---------------------------+
|  PROCESSING PLANE         |
|  Plain text strings       |
|  Chunk arrays             |
|  FAISS index (RAM only)   |
|  Must not log raw content |
+---------------------------+
            |
            | HTTPS
            v
+---------------------------+
|  PRIVILEGED EGRESS        |
|  Third-party LLM APIs     |
|  (Groq / OpenAI)          |
|  Document excerpts sent   |
+---------------------------+
```

| Data Class | Typical Content | At Rest | In Transit |
|---|---|---|---|
| Regulation text | Statutory excerpts, public documents | Temporary directory, deleted after analysis | HTTPS to LLM provider |
| Policy text | Internal privacy statement, potentially confidential | Temporary directory, deleted after analysis | HTTPS to LLM provider |
| Embeddings | Derived dense vectors | RAM only, not persisted | Not transmitted |
| Results JSON | Gap findings, recommendations | `st.session_state` only in cloud deployment | HTTPS to browser |

Production note: sending internal policy text to third-party LLM APIs requires a Data Processing Agreement with the provider and may be subject to data residency constraints. This MVP does not enforce those constraints.

---

## 6. Embedding Provider Selection Logic

```
EMBEDDING_PROVIDER env var
        |
        +-- "local"  --> HuggingFaceEmbeddings(all-MiniLM-L6-v2)
        |
        +-- "openai" --> OpenAIEmbeddings(text-embedding-3-small)
        |                [requires OPENAI_API_KEY]
        |
        +-- "auto"   --> OPENAI_API_KEY set?
                              |
                        yes --+--> OpenAIEmbeddings
                        no  --+--> HuggingFaceEmbeddings
```

The local model is cached by the HuggingFace Hub library after first download. On Streamlit Cloud, `@st.cache_resource` ensures the model is loaded once per deployment instance and reused across sessions.

---

## 7. LLM Provider Selection Logic

```
LLM_PROVIDER env var
        |
        +-- "groq"   --> OpenAI(api_key=GROQ_API_KEY, base_url=groq_base_url)
        |
        +-- "openai" --> OpenAI(api_key=OPENAI_API_KEY)
        |
        +-- "auto"   --> GROQ_API_KEY set?
                              |
                        yes --+--> Groq
                        no  --+--> OPENAI_API_KEY set?
                                         |
                                   yes --+--> OpenAI
                                   no  --+--> RuntimeError
```

---

## 8. Degradation Paths

| Stage | Failure Condition | System Behavior |
|---|---|---|
| Text extraction | Unsupported file extension | ValueError raised; Streamlit displays error, stops analysis |
| Text extraction | Scanned PDF (no text layer) | Returns empty or near-empty string; validation check raises ValueError |
| Policy text too short | Fewer than 50 characters after extraction | ValueError: "Company policy text is too short after extraction" |
| Regulation chunking | Zero chunks produced | ValueError: "Could not chunk regulation text" |
| Summarize LLM call | Non-JSON response | Fallback summary with empty arrays; chunk loop continues |
| Compare LLM call | Non-JSON response | Finding populated with `error: invalid_json`, `risk: medium`, `gap_type: ambiguous_clause` |
| Department LLM call | Non-JSON response | All findings retain empty `departments` arrays |
| API key missing | Both GROQ_API_KEY and OPENAI_API_KEY empty | RuntimeError surfaced in Streamlit error display |

The pipeline is designed to complete and produce a partial result rather than abort on individual LLM failures. This is appropriate for a demo context where a degraded result is more useful than no result.

---

## 9. Deployment Topologies

### A. Local Development

Single process on developer machine. `.env` file provides secrets. Streamlit serves on `127.0.0.1:8501`.

```
Developer machine
+----------------------------------+
|  .venv/                          |
|  streamlit run streamlit_app.py  |
|  .env (gitignored)               |
+----------------------------------+
        |
        v
  http://127.0.0.1:8501
```

### B. Streamlit Community Cloud (current production)

```
GitHub repository
        |
        | webhook on push
        v
Streamlit Cloud runtime
+----------------------------------+
|  streamlit_app.py                |
|  requirements.txt (auto-install) |
|  Secrets dashboard (env vars)    |
|  HF model cache (persistent)     |
+----------------------------------+
        |
        v
  https://your-app.streamlit.app
```

Session state is not shared across users. Each user session runs an independent analysis pipeline. There is no shared database or result cache.

### C. Production-Grade Architecture (recommended path)

For multi-user, high-availability deployment, the synchronous single-process model should be replaced with an async worker architecture:

```
+------------------+     +------------------+     +------------------+
|  Streamlit UI    | --> |  FastAPI gateway  | --> |  Task queue      |
|  (presentation)  |     |  (job submission) |     |  (Redis / SQS)   |
+------------------+     +------------------+     +------------------+
                                                           |
                                                           v
                                                  +------------------+
                                                  |  Worker pool     |
                                                  |  (analysis pods) |
                                                  +------------------+
                                                           |
                                                           v
                                                  +------------------+
                                                  |  Object storage  |
                                                  |  (results JSON)  |
                                                  +------------------+
```

Key changes from current architecture:
- `POST /analyze` returns `202 Accepted` with a job ID immediately
- Workers execute the pipeline asynchronously
- UI polls `GET /results/{job_id}` or receives a webhook
- Results stored in object storage with tenant isolation
- Worker pods scale horizontally for concurrent analyses

---

## 10. Cross-Cutting Concerns

| Concern | Current State | Production Hardening |
|---|---|---|
| Observability | Streamlit default logging | OpenTelemetry spans per pipeline stage; token count tracking per LLM call |
| Rate limiting | None | Per-session or per-user quotas on analysis runs |
| Multi-tenancy | Single shared runtime on Streamlit Cloud | Tenant-prefixed storage; KMS-encrypted result artifacts |
| Model drift | Prompts versioned in Git | Prompt registry with evaluation harness; regression tests on held-out clause pairs |
| Dependency supply chain | requirements.txt with minimum version pins | Lock file (pip-compile); automated vulnerability scanning |
| Authentication | None | OAuth2 / SAML SSO in front of Streamlit; API key rotation policy |

---

## 11. Related Documents

- [methodology.md](methodology.md): RAG formulation, prompt contracts, scoring semantics, failure modes
- [README.md](README.md): Setup commands, environment variable reference, deployment steps, troubleshooting
