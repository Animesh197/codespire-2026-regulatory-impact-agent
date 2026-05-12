# DPDP / GDPR Compliance Impact Agent

**Regulatory impact intelligence** stack built for **Codespire Hackathon 2026**: ingest statutory or internal **regulation text** plus a **company privacy policy**, run **Retrieval-Augmented Generation (RAG)** over policy chunks stored in **FAISS**, synthesize **gap analysis**, **risk tiering**, **remediation hints**, and **department routing**. The service layer is **FastAPI**; the operator UI is **Streamlit**.

This README targets engineers and reviewers who need **runbooks**, **interfaces**, and **operational expectations**—not marketing copy.

---

## Documentation map

| Artifact | Audience | Contents |
|----------|-----------|----------|
| This file | Developers / DevOps | Setup, API, env matrix, troubleshooting |
| [Architecture diagram.md](Architecture%20diagram.md) | Architects | Context diagrams, trust boundaries, deployment shapes |
| [methodology.md](methodology.md) | ML / GRC stakeholders | RAG formulation, prompts, scoring semantics, limits |

---

## Problem framing

| Input | Output |
|-------|--------|
| Regulation artifact (PDF / TXT / DOCX) | Structured **regulation_summary** (obligations, themes) |
| Single company policy artifact | **Findings[]**: gap narrative, gap_type, compliance_status, risk, recommendation, departments |
| — | **Aggregated** posture + heuristic **readiness score** |

The system does **not** certify legal compliance; it **accelerates review** by grounding LLM outputs in **retrieved policy text**.

---

## Architecture snapshot

```
┌─────────────┐     REST      ┌─────────────────────┐     ┌──────────────────┐
│  Streamlit  │ ───────────► │ FastAPI + services  │ ───► │ Groq / OpenAI    │
│  frontend   │               │ RAG + compliance    │     │ (chat); optional │
└─────────────┘               └──────────┬──────────┘     │ OpenAI embed     │
                                         │               └──────────────────┘
                                         ▼
                               ┌─────────────────────┐
                               │ FAISS + embeddings  │
                               │ (local MiniLM or    │
                               │  OpenAI vectors)    │
                               └─────────────────────┘
```

Detailed diagrams: [Architecture diagram.md](Architecture%20diagram.md).

---

## Feature capability matrix

| Capability | Implementation | Notes |
|------------|----------------|--------|
| Upload validation | `backend/utils/file_validation.py` | Extensions + byte cap |
| PDF / DOCX / TXT extraction | `backend/services/extraction.py` | DOCX = body paragraphs (tables weak) |
| Semantic chunking | `backend/services/chunking.py` | Recursive splitter; size/overlap via config |
| Embeddings | `backend/services/embeddings.py` | **auto**: OpenAI if key + provider path; else **local** MiniLM |
| Vector index | `backend/services/vector_store.py` | In-memory FAISS per request |
| Gap synthesis | `backend/services/compliance_engine.py` | N regulation chunks × (retrieve + LLM) |
| Prompt assets | `backend/prompts/*.txt` | Version in Git; no runtime prompt DB |

---

## Requirements

| Dependency class | Detail |
|------------------|--------|
| Runtime | Python **3.10+** (CI/dev validated on 3.14 in workspace) |
| Network | Groq and/or OpenAI APIs; Hugging Face Hub on **first** local embedding pull |
| Disk | Upload + result JSON under `data/`; HF cache under user home by default |
| RAM | sentence-transformers + FAISS modest for demo-sized docs; scale horizontally for huge PDFs |

---

## Installation

```bash
git clone https://github.com/Animesh197/codespire-2026-regulatory-impact-agent.git
cd codespire-2026-regulatory-impact-agent
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # edit secrets locally — never commit
```

---

## Environment variables (reference)

Loaded via `pydantic-settings` from **repository-root** `.env`. Names are **case-insensitive** per Pydantic.

| Variable | Required | Purpose |
|----------|----------|---------|
| `GROQ_API_KEY` | One of Groq / Open | Groq inference (`gsk_...`) |
| `OPENAI_API_KEY` | Optional | GPT chat and/or embeddings (`sk-...`) |
| `LLM_PROVIDER` | Optional | `auto` (default), `groq`, `openai` — overrides auto-selection |
| `GROQ_MODEL` | Optional | e.g. `llama-3.3-70b-versatile` |
| `OPENAI_MODEL` | Optional | e.g. `gpt-4o` |
| `EMBEDDING_PROVIDER` | Optional | `auto` (default), `local`, `openai` |
| `EMBEDDING_MODEL` | Optional | OpenAI embedding id when provider is OpenAI |
| `LOCAL_EMBEDDING_MODEL` | Optional | Hugging Face sentence-transformers id |

**Resolution rules (concise):**

- **LLM (`resolved_llm_provider`)**: explicit `LLM_PROVIDER` wins; else if `GROQ_API_KEY` set → Groq; else if `OPENAI_API_KEY` → OpenAI; else error.
- **Embeddings (`resolved_embedding_provider`)**: `EMBEDDING_PROVIDER=local` forces local MiniLM; `openai` requires OpenAI key; **auto** picks OpenAI embeddings only when `OPENAI_API_KEY` is non-empty, else **local**.

---

## Runbooks

### API (development)

```bash
cd codespire-2026-regulatory-impact-agent    # repo root must contain backend/
source .venv/bin/activate
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

| Endpoint | Use |
|----------|-----|
| `GET /health` | Liveness |
| `GET /docs` | OpenAPI UI |

### Streamlit UI

```bash
source .venv/bin/activate
streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Point the sidebar **API base URL** at `http://127.0.0.1:8000`.

### Sample corpus

- `data/samples/sample_regulation.txt`
- `data/samples/sample_company_policy.txt`

---

## REST API — examples

**Upload** (multipart field names are fixed):

```bash
curl -s -X POST http://127.0.0.1:8000/upload \
  -F "regulation=@data/samples/sample_regulation.txt" \
  -F "company_policy=@data/samples/sample_company_policy.txt"
```

Response contains `job_id`.

**Analyze** (may take minutes — Groq latency × chunk count):

```bash
curl -s -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"job_id":"<paste-uuid>"}'
```

**Fetch cached result**:

```bash
curl -s "http://127.0.0.1:8000/results?job_id=<paste-uuid>"
```

---

## Operational characteristics

| Dimension | Behavior |
|-----------|----------|
| **Latency drivers** | `max_regulation_chunks_for_compare` × (1 LLM compare + retrieval); +1 summarize +1 department call |
| **Cost drivers** | Groq/OpenAI tokens; optional OpenAI embedding API |
| **Determinism** | Low — LLM temperature > 0; retrieval ties may vary slightly |
| **Idempotency** | Re-POST `/analyze` overwrites `data/results/<job_id>.json` |
| **Concurrency** | MVP uses sync handlers — parallel uploads risk blocking; production should queue |

---

## Repository layout

```
codespire-2026-regulatory-impact-agent/
├── backend/
│   ├── api/                 # routes, Pydantic schemas
│   ├── services/            # extraction, chunking, embeddings, vector_store, rag, llm, compliance_engine
│   ├── prompts/             # *.txt prompt contracts
│   ├── utils/               # config, validation, text_clean
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   ├── app.py
│   ├── services/api_client.py
│   └── styles/custom.css
├── data/uploads|results|samples/
├── requirements.txt         # rolls up backend + frontend
├── Architecture diagram.md
├── methodology.md
└── README.md
```

---

## Security & compliance posture (engineering)

| Topic | MVP status | Recommendation |
|-------|------------|----------------|
| Secrets | `.env` gitignored | Managed secrets in cloud |
| CORS | Permissive (`*`) | Restrict to UI origin |
| AuthN/Z | None | JWT / mTLS / API gateway |
| Uploaded content | Plain paths on disk | AV scan, customer-isolated buckets |
| PII in logs | Avoid logging bodies | Structured logs without raw policy text |

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|----------------|--------|
| `503` / RuntimeError on keys | Missing `GROQ_API_KEY` / `OPENAI_API_KEY` | Fix `.env`; see resolution rules |
| Analyze timeout | Too many chunks or slow LLM | Lower `MAX_REGULATION_CHUNKS_FOR_COMPARE` in env (extend Settings if needed) or shorten PDF |
| Empty / odd summary | LLM JSON parse failure | Engine degrades gracefully; check `results` JSON |
| First run slow | HF model download | Wait; set `HF_HOME` if offline cache needed |

---

## License

See [LICENSE](LICENSE) (**Apache-2.0**). This hackathon build provides decision-support analytics only—not legal certification.

## Bundled demo PDFs (repository root)

| File | Use |
|------|-----|
| `DPDP_Regulation_Sample.pdf` | Regulation-side sample |
| `Incomplete_Company_Privacy_Policy.pdf` | Policy-side sample (incomplete by design for gap testing) |

Upload via **Streamlit**, or use `data/samples/*.txt` for faster smoke tests.
