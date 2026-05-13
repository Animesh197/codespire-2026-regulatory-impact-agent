# DPDP / GDPR Compliance Impact Agent

A regulatory impact intelligence system built for Codespire Hackathon 2026. The system ingests a statutory regulation artifact and a company privacy policy, executes a Retrieval-Augmented Generation pipeline over semantically chunked policy text stored in an in-memory FAISS index, and synthesizes structured gap analysis, risk tiering, remediation guidance, and department ownership routing. The entire stack runs as a single Streamlit application with no separate API server.

---

## Documentation Map

| Artifact | Audience | Contents |
|---|---|---|
| README.md (this file) | Engineers, reviewers | Setup, configuration, deployment, troubleshooting |
| [Architecture diagram.md](Architecture%20diagram.md) | Architects, technical leads | Component topology, trust boundaries, sequence flows, deployment shapes |
| [methodology.md](methodology.md) | ML engineers, GRC stakeholders | RAG formulation, prompt contracts, scoring semantics, failure modes |

---

## Problem Statement

| Input | Output |
|---|---|
| Regulation artifact (PDF / TXT / DOCX) | Structured `regulation_summary`: obligations, compliance requirements, data subject rights, security duties, transfer rules |
| Company privacy policy artifact (PDF / TXT / DOCX) | `findings[]`: gap narrative, gap_type, compliance_status, risk tier, recommendation, department assignments |
| Both documents | Aggregated compliance posture + heuristic readiness score (0-100) |

The system does not certify legal compliance. It accelerates expert review by grounding every LLM inference in retrieved policy text, making the evidence chain auditable.

---

## Architecture Overview

```
+--------------------------------------------------+
|              streamlit_app.py                    |
|                                                  |
|  Upload UI  -->  extract()  -->  split_text()    |
|                                                  |
|  build_faiss_index(policy_chunks)                |
|         |                                        |
|         v                                        |
|  for each reg_chunk:                             |
|    retrieve_context(store, reg_chunk)            |
|    chat_json(PROMPT_COMPARE, ...)                |
|         |                                        |
|         v                                        |
|  chat_json(PROMPT_SUMMARIZE, regulation)         |
|  chat_json(PROMPT_DEPT, issues[])                |
|         |                                        |
|         v                                        |
|  Results dashboard (metrics, tabs, JSON export)  |
+--------------------------------------------------+
              |                    |
              v                    v
     Groq / OpenAI API     HuggingFace Hub
     (LLM inference)       (local MiniLM weights,
                            first run only)
```

All processing is in-process within the Streamlit runtime. There is no HTTP boundary between the UI and the analysis logic. Uploaded files are written to a temporary directory scoped to the session and discarded after analysis.

---

## Capability Matrix

| Capability | Location in codebase | Notes |
|---|---|---|
| File validation | `streamlit_app.py` upload block | Extension whitelist: pdf, txt, docx; byte cap enforced |
| Text extraction | `extract_text()` | PyMuPDF for PDF; python-docx for DOCX; multi-encoding fallback for TXT |
| Semantic chunking | `split_text()` | RecursiveCharacterTextSplitter; 800-char target, 120-char overlap |
| Embeddings | `get_embeddings()` | Auto-selects OpenAI if key present, else local MiniLM (sentence-transformers) |
| Vector index | `build_faiss_index()` | In-memory FAISS per analysis session; normalized inner-product search |
| RAG retrieval | `retrieve_context()` | Top-K policy chunks per regulation chunk; K=5 default |
| Gap synthesis | `run_analysis()` | N regulation chunks x (retrieve + LLM compare); structured JSON per finding |
| Regulation summary | `chat_json(PROMPT_SUMMARIZE, ...)` | Single LLM call; thematic arrays |
| Department routing | `chat_json(PROMPT_DEPT, ...)` | Single LLM call over all findings; fixed department taxonomy |
| Prompt contracts | Inline constants in `streamlit_app.py` | Versioned with code; no runtime prompt database |
| Results export | Streamlit download button | Full JSON report including policy_stats and all findings |

---

## Requirements

| Category | Specification |
|---|---|
| Python | 3.10 or higher |
| LLM provider | Groq API key (recommended) or OpenAI API key; at least one required |
| Embedding provider | Auto-selected: OpenAI if key present, else local sentence-transformers (no key required) |
| Network | Outbound HTTPS to Groq/OpenAI; HuggingFace Hub on first local embedding model download |
| Memory | sentence-transformers + FAISS are modest for demo-scale documents; large PDFs (100+ pages) will increase RAM and latency proportionally |

---

## Local Setup

```bash
git clone https://github.com/Animesh197/codespire-2026-regulatory-impact-agent.git
cd codespire-2026-regulatory-impact-agent
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set GROQ_API_KEY
streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501` in a browser.

---

## Environment Variables

The application reads configuration from environment variables. Locally these are loaded from `.env` via `python-dotenv`. On Streamlit Cloud they are read from the Secrets dashboard.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GROQ_API_KEY` | One of Groq or OpenAI | — | Groq inference endpoint authentication |
| `OPENAI_API_KEY` | One of Groq or OpenAI | — | OpenAI chat and/or embedding authentication |
| `LLM_PROVIDER` | No | `auto` | Force provider: `groq`, `openai`, or `auto` |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model identifier |
| `OPENAI_MODEL` | No | `gpt-4o` | OpenAI model identifier |
| `EMBEDDING_PROVIDER` | No | `auto` | Force embedding: `local`, `openai`, or `auto` |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model identifier |
| `LOCAL_EMBEDDING_MODEL` | No | `sentence-transformers/all-MiniLM-L6-v2` | HuggingFace model identifier for local embeddings |

**Provider resolution logic:**

- LLM: explicit `LLM_PROVIDER` takes precedence; otherwise Groq if `GROQ_API_KEY` is set; otherwise OpenAI if `OPENAI_API_KEY` is set; otherwise runtime error.
- Embeddings: `local` forces MiniLM; `openai` requires `OPENAI_API_KEY`; `auto` selects OpenAI only when `OPENAI_API_KEY` is non-empty, otherwise local.

---

## Streamlit Cloud Deployment

1. Push the repository to GitHub.
2. Log in to [share.streamlit.io](https://share.streamlit.io) with GitHub.
3. Create a new app:
   - Repository: `Animesh197/codespire-2026-regulatory-impact-agent`
   - Branch: `main`
   - Main file path: `streamlit_app.py`
4. Under Advanced settings, open the Secrets editor and add:

```toml
GROQ_API_KEY = "gsk_your_key_here"
GROQ_MODEL   = "llama-3.3-70b-versatile"
```

5. Deploy. The first deployment downloads the local embedding model (~90 MB) and caches it for subsequent runs.

---

## Sample Documents

| File | Purpose |
|---|---|
| `DPDP_Regulation_Sample.pdf` | Regulation-side input sample (DPDP Act excerpts) |
| `Incomplete_Company_Privacy_Policy.pdf` | Policy-side input sample (intentionally incomplete for gap demonstration) |
| `data/samples/sample_regulation.txt` | Plain-text regulation sample for faster smoke tests |
| `data/samples/sample_company_policy.txt` | Plain-text policy sample |

---

## Operational Characteristics

| Dimension | Behavior |
|---|---|
| Latency | Dominated by `max_reg_chunks` x LLM round-trip latency; one additional call each for summarization and department mapping |
| Cost | Groq/OpenAI token consumption proportional to document length and chunk count; local embeddings eliminate embedding API cost |
| Determinism | Low; LLM temperature > 0 and retrieval tie-breaking introduce run-to-run variation |
| Concurrency | Streamlit sessions are isolated; each session runs its own analysis pipeline in-process |
| State | Analysis results are held in `st.session_state`; no disk persistence in the cloud deployment |

---

## Repository Layout

```
codespire-2026-regulatory-impact-agent/
├── streamlit_app.py          # Complete application: config, extraction, chunking,
│                             # embeddings, FAISS, RAG, LLM, compliance engine, UI
├── requirements.txt          # All dependencies
├── .env.example              # Environment variable reference
├── .streamlit/
│   └── secrets.toml.example  # Streamlit Cloud secrets reference
├── data/
│   ├── samples/              # Plain-text test corpus
│   └── results/              # Local result cache (gitignored except .gitkeep)
├── DPDP_Regulation_Sample.pdf
├── Incomplete_Company_Privacy_Policy.pdf
├── Architecture diagram.md
├── methodology.md
└── README.md
```

---

## Security Posture

| Topic | Current State | Production Recommendation |
|---|---|---|
| Secrets | `.env` gitignored; Streamlit secrets dashboard on cloud | Managed secrets service (AWS Secrets Manager, GCP Secret Manager) |
| Uploaded content | Temporary directory, discarded after analysis | AV scanning; customer-isolated ephemeral storage |
| LLM data egress | Document excerpts sent to third-party APIs | Review DPA with Groq/OpenAI; enforce data residency constraints |
| Authentication | None | OAuth2 / SAML SSO in front of Streamlit |
| PII in logs | Streamlit default logging does not capture file content | Structured logging with explicit PII exclusion |

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| RuntimeError on API key | `GROQ_API_KEY` and `OPENAI_API_KEY` both empty | Set at least one key in `.env` or Streamlit secrets |
| Analysis times out or is very slow | Too many regulation chunks or high LLM latency | Reduce document length or lower `max_reg_chunks` in `_Cfg` |
| All findings show `invalid_json` | Model returning non-JSON; prompt/model mismatch | Verify model name; try a different Groq model |
| First run takes several minutes | HuggingFace model download (~90 MB) | Wait for download to complete; subsequent runs use cache |
| Empty regulation summary | LLM JSON parse failure on summarize call | Check `regulation_summary` key in exported JSON for raw error |

---

## License

Apache-2.0. See [LICENSE](LICENSE). This system provides decision-support analytics only and does not constitute legal advice or regulatory certification.
