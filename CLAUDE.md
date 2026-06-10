# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**IR-Copilot** — a grounded, multi-agent Investor-Relations workflow that turns a ticker +
quarter into an earnings-call **script**, **deck outline**, and **Q&A cheat sheet**. It is a
hackathon project targeting an **AMD MI300X (ROCm + vLLM)** serving node. The authoritative
design lives in `docs/` (a MkDocs site); `PLAN.md` is the older single-file summary.

The implementation is the `src/ir_copilot/` package; `notebooks/01..08` are step-by-step,
runnable demonstrations built on top of it; `api/server.py` exposes everything over HTTP.

## Two Python environments (important)

- **System `python3` (3.9.6)** — runs offline: notebooks, package smoke tests, the server in
  mock mode. Use `python3 -m pip`, not bare `pip`.
- **`.venv312` (Python 3.12)** — required for **live** `defeatbeta-api` and the mock-data
  builder (the package needs 3.11+ and downloads a DuckDB extension + HF parquet on first use).

```bash
# Setup
cp .env.example .env
python3 -m pip install -r requirements.txt           # core
# live data / server with live data → a 3.12 venv:
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -r requirements.txt -r requirements-live.txt
# requirements-gpu.txt (vLLM, unsloth, whisper) installs ONLY on the MI300X node

# Run / "test" a notebook headless (nbconvert aborts on any error → this IS the test)
PYTHONPATH=src python3 -m nbconvert --to notebook --execute --inplace notebooks/06_drafting_and_grounding.ipynb

# Package smoke test (note PYTHONPATH=src — the package is under src/)
PYTHONPATH=src python3 -c "from ir_copilot.graph import build_graph; print('ok')"

# API server (mock mode works on 3.9; live needs .venv312 + USE_MOCK_DATA=false)
PYTHONPATH=src python3 -m uvicorn ir_copilot.api.server:app --port 8088
curl -s http://127.0.0.1:8088/health

# Rebuild the cached real data for NVDA/AMD/TSLA (3.12 + network)
.venv312/bin/python mock/build_mock_data.py

# Docs
python3 -m mkdocs build --strict       # fails on broken links — run before committing docs
```

- There is **no pytest suite**. Verification = executing notebooks (inline `assert`s), the
  package smoke test, and hitting the running API with `curl`.
- **Bash runs sandboxed (no network).** Anything touching defeatbeta-api / HuggingFace / the
  DuckDB extension (the mock builder, live mode, starting the server) needs the network — run
  those Bash calls with `dangerouslyDisableSandbox: true`.
- Notebook asserts must stay robust to **real** data — don't assert on specific values/themes
  (e.g. "a concern theme exists"); assert structural facts (results returned, verification
  passes, hallucinated number caught).

## Configuration — everything comes from `.env`

`src/ir_copilot/config.py` loads `.env` (anchored to the repo root, so it works from any cwd)
into a frozen `settings` object. Never hard-code settings; add a field to `Settings` +
`get_settings()` + both env files. Key swappable backends:

| Env var | Values | Effect |
|---|---|---|
| `USE_MOCK_DATA` | `true` / `false` | cached **real** data (`mock/data/`) vs live defeatbeta-api |
| `QDRANT_MODE` | `memory` / `docker` / `local` | vector store transport (docker falls back to memory if unreachable) |
| `EMBEDDING_BACKEND` | `hash` / `sentence-transformers` / `vllm` | `hash` = offline, zero-download |
| `SENTIMENT_BACKEND` | `finbert` (default) / `lexicon` | FinBERT needs torch; auto-falls back to lexicon if torch absent |
| `LLM_BACKEND` | `mock` / `vllm` | deterministic templates vs MI300X endpoints |

**Offline ≠ fake.** `USE_MOCK_DATA=true` reads **cached real defeatbeta-api data** from
`mock/data/*.json` (built by `mock/build_mock_data.py` for NVDA/AMD/TSLA over ~5y) — real
financials, real news article links, real analyst-Q&A transcript provenance. **Never reintroduce
placeholder URLs (example.com) or invented numbers.** Going live on the MI300X is an `.env` flip
(`USE_MOCK_DATA=false`, `*_BACKEND=vllm`, `QDRANT_MODE=docker`); **no agent code changes**.

## Architecture & critical invariants

Pipeline (LangGraph state machine in `graph.py`):
`extract → wiki → sentiment → compare → predict → draft → verify → [human interrupt] → finalize`,
with a conditional edge from `verify` back to `draft` on grounding failure.

Things you must understand before editing — they require reading multiple files:

1. **Numbers are data, never generated (the no-hallucination guarantee).** Financial values live
   only in the `FactStore` (`facts.py`). The drafting agent writes **slots** (`{{F-00xx}}` via
   `store.slot(metric)`); `render_slots()` substitutes verified values; the **Grounding Verifier**
   (`agents/verify.py`) extracts every number from the rendered text and fails the draft if any
   isn't traceable to a fact. When changing drafting/verification, keep numbers flowing through
   slots — do not let an agent emit a bare figure. The number regex deliberately ignores digits
   embedded in tokens like `FY2026Q1`.

2. **Graph state must be JSON/msgpack-serializable** (the checkpointer persists it across the
   human interrupt). Therefore: state holds only pydantic models / lists / dicts — **not**
   `FactStore` or `WikiStore` (their Qdrant client and plain class aren't serializable). The
   `FactStore` is rebuilt inside each node via `FactStore.from_facts(...)`; the Qdrant wiki is a
   **process-level singleton** (`graph._get_wiki()`). If you add a node, follow this pattern or
   the checkpoint will raise `Type is not msgpack serializable`.

3. **Agents are backend-agnostic.** Each agent that uses an LLM takes an optional `chat` arg
   (`llm.get_chat(role)` returns `None` in mock mode). Mock = deterministic grounded templates;
   `vllm` = real model phrases/ranks but is held to the same slot/grounding discipline. The
   Predictive Analyst (`agents/predictive.py`) is the **fine-tuning target** (`docs/finetuning.md`,
   `notebooks/08`).

4. **Provenance everywhere.** Facts carry `source`/`source_url`; wiki chunks carry `source_url`;
   sentiment themes and peer metrics carry the source items / `fact_ids`. Keep new outputs cited.

## Data path & module map

`build_fact_store(use_mock)` branches: **mock** → `mockdata.py` reads `mock/data/*.json`;
**live** → `live.py` calls the real defeatbeta-api (verified method names + value columns +
fraction→percent conversion live here). `corpus.py` does the same branch for news/transcripts.
`service.py` is the capability layer (facts/sentiment/competitor/questions/draft/wiki, cached in
SQLite via `cache.py`); both `api/server.py` (FastAPI + CopilotKit) and the notebooks call it.
`graph.py` wires the agents into the LangGraph state machine.

To refresh cached real data (3.12 + network): `.venv312/bin/python mock/build_mock_data.py`.

**Production persistence guarantee:** every ticker queried in live mode is fully persisted
to SQLite (`cache.py: ticker_data` table) so subsequent calls and server restarts never re-hit
the live API within the TTL (24h for facts/wiki/signals, 6h for news). The Qdrant wiki is
rebuilt from SQLite on startup — no network required. Cache management API: `GET /api/cache`,
`DELETE /api/cache/{ticker}`.

## Conventions

- Notebooks are the single source of truth (no generator scripts). A notebook's first code cell
  adds `src/` to `sys.path` by walking up to the repo root, then imports `ir_copilot`.
- The `docs/` MkDocs pages are the design spec — when you change behavior, update the matching
  page and re-run `mkdocs build --strict`.
- `mock/data/*.json` is committed real evidence (un-ignored despite the `data/` rule). Other
  generated artifacts (`artifacts/`, `site/`, models, `.env`, `.venv*`) are git-ignored.
