# Architecture — Advanced technical views

This document complements [README.md](README.md) with **architectural reasoning**: trust boundaries, deployment topologies, failure domains, and component responsibilities suitable for design reviews.

---

## 1. Design goals

| Goal | Mechanism |
|------|-----------|
| **Evidence-linked outputs** | Policy chunks retrieved into the LLM context for every regulation slice |
| **Provider portability** | OpenAI SDK + swappable `base_url` for Groq |
| **Cost-aware demos** | Local embeddings path avoids OpenAI vector charges |
| **Inspectable artifacts** | JSON snapshots under `data/results/` |

---

## 2. C4-style layering (conceptual)

### Level 1 — System context

```mermaid
flowchart TB
  subgraph org [Organization boundary]
    U[Privacy / GRC analyst]
  end
  subgraph sys [Compliance Impact Agent]
    UI[Web UI\nStreamlit]
    API[HTTP API\nFastAPI]
  end
  subgraph world [External systems]
    LLM[(LLM inference\nGroq / OpenAI)]
    EMB[(Embedding API\noptional OpenAI)]
    HF[(HF Hub\nmodel weights)]
  end
  U --> UI
  UI --> API
  API --> LLM
  API --> EMB
  API --> HF
```

### Level 2 — Containers

| Container | Technology | Responsibility |
|-----------|------------|----------------|
| **Presentation** | Streamlit (`frontend/app.py`) | Upload UX, metrics, tabular findings, JSON export |
| **Application API** | FastAPI (`backend/main.py`, `backend/api/routes.py`) | Multipart ingest, orchestrate analysis, serve cached JSON |
| **Analysis core** | Python services (`backend/services/*`) | Extract → chunk → embed → FAISS → RAG loops → aggregate |
| **Prompt library** | Text files (`backend/prompts/*.txt`) | Frozen prompt contracts versioned with code |
| **Local persistence** | Filesystem (`data/uploads`, `data/results`) | MVP durable store |

---

## 3. Component interaction (detailed)

```mermaid
flowchart LR
  subgraph routes [API layer]
    RU[POST /upload]
    RA[POST /analyze]
    RG[GET /results]
  end
  subgraph svc [Services]
    EX[extraction]
    CH[chunking]
    EM[embeddings]
    VS[vector_store / FAISS]
    RG2[rag.retrieve]
    LL[llm.chat_*]
    CE[compliance_engine]
  end
  subgraph io [IO]
    UP[(uploads/job_id/*)]
    RS[(results/job_id.json)]
  end
  RU --> EX
  RA --> CE
  CE --> EX
  CE --> CH
  CE --> EM --> VS
  CE --> RG2 --> VS
  CE --> LL
  RU --> UP
  RA --> UP
  CE --> RS
  RG --> RS
```

---

## 4. Trust boundaries and data classification

```mermaid
flowchart TB
  subgraph untrusted [Untrusted input plane]
    DOC[Uploaded PDF/DOCX/TXT]
  end
  subgraph processing [Processing plane — must not log raw content in prod]
    P[Parse + chunk + embed]
    IDX[FAISS index in RAM]
  end
  subgraph privileged [Privileged egress]
    LLMNET[Third-party LLM APIs]
  end
  DOC --> P --> IDX
  P --> LLMNET
```

| Data class | Typical content | At-rest (MVP) | In transit |
|------------|-----------------|---------------|------------|
| **Regulation text** | Statutory excerpts | `data/uploads/.../regulation.*` | HTTPS to LLM provider |
| **Policy text** | Internal privacy statement | Same job folder | HTTPS to LLM provider |
| **Embeddings** | Derived vectors | RAM only | — |
| **Results JSON** | Gaps + recommendations | `data/results/*.json` | HTTPS to Streamlit host |

**Important:** production systems should classify uploads as **confidential**, minimize retention, and avoid shipping raw documents to LLMs without **DPA** and **region** constraints—this MVP sends excerpts as required for analysis.

---

## 5. Sequence — successful analyze path

```mermaid
sequenceDiagram
  autonumber
  participant C as Client
  participant A as FastAPI
  participant F as Job FS
  participant E as compliance_engine
  participant V as FAISS
  participant L as LLM API

  C->>A: POST /analyze {job_id}
  A->>F: glob regulation.*, policy.*
  A->>E: run_compliance_analysis
  E->>E: extract + chunk policy/regulation
  E->>V: build index(policy_chunks)
  E->>L: summarize(regulation) JSON
  loop i in 0..min(N, max_chunks)
    E->>V: similarity_search(reg_chunk_i, k)
    E->>L: compare(reg_chunk_i, policy_ctx) JSON
  end
  E->>L: departments(issues[]) JSON
  E-->>A: aggregate payload
  A->>F: write results JSON
  A-->>C: 200 + results envelope
```

---

## 6. Sequence — degradation paths

| Stage | Failure | System behavior |
|-------|---------|-------------------|
| Upload | Bad extension / oversize | `400`, job dir removed |
| Analyze | Missing job dir | `404` |
| Summarize LLM | Non-JSON | Empty structured summary; chunk loop continues |
| Compare LLM | Non-JSON | Finding row with `ambiguous_clause` + snippet |
| Dept LLM | Non-JSON | Departments omitted (empty arrays) |
| Keys missing | Resolution throws | `503` / RuntimeError surfaced via HTTP |

---

## 7. Deployment topologies

### A. Developer laptop (default)

Streamlit and Uvicorn on `127.0.0.1`; `.env` on disk; single-user.

### B. Split UI and API (staging)

```mermaid
flowchart LR
  subgraph pub [Public edge — TLS]
    ST[Streamlit Cloud / static host]
  end
  subgraph vpc [Private network]
    API[FastAPI behind reverse proxy]
  end
  ST -->|HTTPS + API key| API
```

Rotate secrets in platform vault; restrict CORS to Streamlit origin.

### C. Future — async workers

```mermaid
flowchart LR
  API[FastAPI] --> Q[(Redis / SQS)]
  Q --> W[Worker pods]
  W --> OBJ[(Object storage)]
  W --> LLM[(LLM)]
  API --> POLL[GET /results async job id]
```

Replace synchronous `/analyze` with **202 Accepted** + polling or Webhook.

---

## 8. Cross-cutting concerns checklist

| Concern | MVP | Hardening |
|---------|-----|-----------|
| **Observability** | Print / uvicorn logs | OpenTelemetry spans per stage + token counts |
| **Rate limits** | None | Per-tenant quotas on `/analyze` |
| **Multi-tenancy** | Single disk tree | Prefix uploads by `tenant_id` + KMS |
| **Model drift** | Prompts in Git | Prompt registry + evaluation harness |

---

## 9. Related reading

- [methodology.md](methodology.md) — formal RAG + scoring semantics  
- [README.md](README.md) — commands and env matrix  
