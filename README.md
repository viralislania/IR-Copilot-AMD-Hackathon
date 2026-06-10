# IR-Copilot

**Autonomous Earnings-Call Script, Deck & Q&A Cheat-Sheet** — a grounded, multi-agent
Investor-Relations workflow on **AMD MI300X (ROCm + vLLM)**. It ingests a company's quarterly
financials, benchmarks peers, predicts the hardest investor questions, and drafts a compliant
earnings-call script + deck outline + CEO/CFO Q&A cheat sheet — with **every number traced to
real defeatbeta-api evidence** and a **human approval gate**.

Full design docs: `docs/` (run `mkdocs serve`). This README is how to get the code running.

---

## Two ways to run

| Mode | Data | Python | Needs |
|---|---|---|---|
| **Offline (default)** | cached **real** defeatbeta-api data in `mock/data/` | 3.9+ | nothing external |
| **Live** | fresh from **defeatbeta-api** | **3.11+** | network |

Offline mode is real evidence (facts, news links, transcript Q&A for NVDA/AMD/TSLA) — not
placeholders — so demos are reproducible with no network or GPU. Switch with `USE_MOCK_DATA`.

---

## Quick start (offline)

```bash
cp .env.example .env
python3 -m pip install -r requirements.txt

# Run the step notebooks (each is self-checking)
PYTHONPATH=src python3 -m jupyter notebook notebooks/

# Or start the API server
PYTHONPATH=src python3 -m uvicorn ir_copilot.api.server:app --port 8088
curl -s http://127.0.0.1:8088/health
```

## Live data + server (Python 3.11+)

`defeatbeta-api` needs Python 3.11+ (it downloads a DuckDB extension + HuggingFace parquet on
first use). Use a dedicated venv:

```bash
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -r requirements.txt -r requirements-live.txt

# Refresh the cached real data for NVDA / AMD / TSLA (past ~5y)
.venv312/bin/python mock/build_mock_data.py

# Live mode: set USE_MOCK_DATA=false in .env, then
PYTHONPATH=src .venv312/bin/python -m uvicorn ir_copilot.api.server:app --reload --port 8088
```

---

## The API (all functionality is exposed)

| Endpoint | What |
|---|---|
| `GET /health` | status + active backends |
| `GET /api/facts/{ticker}` | Financial Fact Store (grounded, with sources) |
| `GET /api/sentiment/{ticker}` | news sentiment + themes (FinBERT) |
| `GET /api/competitor/{ticker}` | peer comparison (leads/lags) |
| `GET /api/questions/{ticker}` | predicted hard investor questions + evidence |
| `GET /api/draft/{ticker}` | script + deck outline + Q&A cheat sheet + verification |
| `GET /api/wiki/search?q=&ticker=&k=` | retrieve cited transcript passages |
| `GET /api/run/{ticker}/stream` | **SSE** — streams agent updates, pauses at the human gate |
| `POST /api/run/{ticker}/resume` | resume after human approve/edit |
| `POST /copilotkit` | **CopilotKit AG-UI** endpoint for the React frontend |

```bash
# Stream the full run, then approve
curl -N http://127.0.0.1:8088/api/run/NVDA/stream
curl -X POST http://127.0.0.1:8088/api/run/NVDA/resume \
     -H 'Content-Type: application/json' \
     -d '{"thread_id":"NVDA-FY2026Q2","decision":"approve"}'
```

**CopilotKit frontend:** point a CopilotKit React app's runtime URL at `/copilotkit`; it drives
the same LangGraph agent over AG-UI (`useCoAgent`, `useCoAgentStateRender`,
`useLangGraphInterrupt`). See `docs/ui.md`.

---

## Configuration (`.env` — all behavior is here)

| Var | Values | Notes |
|---|---|---|
| `USE_MOCK_DATA` | `true`/`false` | cached real data vs live defeatbeta-api |
| `QDRANT_MODE` | `memory`/`docker`/`local` | vector store transport |
| `EMBEDDING_BACKEND` | `hash`/`sentence-transformers`/`vllm` | `hash` = offline |
| `SENTIMENT_BACKEND` | `finbert`/`lexicon` | **finbert default** (falls back to lexicon if torch absent) |
| `LLM_BACKEND` | `mock`/`vllm` | `vllm` = MI300X endpoints |
| `DEMO_TICKER` / `PEER_TICKERS` | e.g. `NVDA` / `AMD,TSLA` | tickers with cached data |

Going live on the **MI300X**: flip `LLM_BACKEND=vllm`, `EMBEDDING_BACKEND=vllm`,
`USE_MOCK_DATA=false`, `QDRANT_MODE=docker`. No agent code changes (`docs/rocm-vllm.md`).

---

## Layout

```
src/ir_copilot/      package: config, facts, live, cache(sqlite), embeddings, vectorstore,
                     llm, corpus, mockdata, service, graph, agents/, api/(FastAPI+CopilotKit)
mock/                build_mock_data.py + data/*.json  (cached REAL defeatbeta-api evidence)
notebooks/           01..08 step-by-step, runnable offline
docs/                MkDocs design site   ·   PLAN.md, CLAUDE.md
```

Persistence is **SQLite** (`artifacts/ir_copilot.sqlite`, git-ignored) — no parquet/duckdb in
IR-Copilot itself (`duckdb` is only a transitive dep of defeatbeta-api). Fine-tuning (Unsloth,
the critical feature) runs on the MI300X — `notebooks/08`, `docs/finetuning.md`.
