# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**IR-Copilot** — a grounded, multi-agent Investor-Relations workflow that turns a ticker +
quarter into an earnings-call **script**, **deck outline**, and **Q&A cheat sheet**. It is a
hackathon project targeting an **AMD MI300X (ROCm + vLLM)** serving node. The authoritative
design lives in `docs/` (a MkDocs site); `PLAN.md` is the older single-file summary.

The implementation is the `src/ir_copilot/` package; `notebooks/01..08` are step-by-step,
runnable demonstrations built on top of it.

## Commands

```bash
# Setup
cp .env.example .env
python3 -m pip install -r requirements.txt          # core (cross-platform)
# requirements-gpu.txt (vLLM, unsloth, whisper) installs ONLY on the MI300X/ROCm node

# Run / "test" a step notebook headless (nbconvert aborts on any error → this IS the test)
python3 -m nbconvert --to notebook --execute --inplace notebooks/06_drafting_and_grounding.ipynb

# Smoke-test the package directly (note PYTHONPATH=src — the package is under src/)
PYTHONPATH=src python3 -c "from ir_copilot.graph import build_graph; print('ok')"

# Docs site
python3 -m mkdocs serve                # http://127.0.0.1:8000
python3 -m mkdocs build --strict       # fails on broken links — run before committing docs
```

- `python3` is the interpreter (system Python 3.9.6). Use `python3 -m pip`, not bare `pip`.
- There is **no pytest suite**. Verification = executing notebooks (they contain inline
  `assert`s) plus ad-hoc `PYTHONPATH=src python3 -c "..."` smoke scripts.
- `defeatbeta-api` needs Python 3.11+; it is only reached when `USE_MOCK_DATA=false`. Everything
  else runs on 3.9.

## Configuration — everything comes from `.env`

`src/ir_copilot/config.py` loads `.env` (anchored to the repo root, so it works from any cwd)
into a frozen `settings` object. Never hard-code settings; add a field to `Settings` +
`get_settings()` + both env files. Key swappable backends:

| Env var | Values | Effect |
|---|---|---|
| `USE_MOCK_DATA` | `true` / `false` | deterministic mock financials vs live defeatbeta-api |
| `QDRANT_MODE` | `memory` / `docker` / `local` | vector store transport (docker falls back to memory if unreachable) |
| `EMBEDDING_BACKEND` | `hash` / `sentence-transformers` / `vllm` | `hash` = offline, zero-download |
| `SENTIMENT_BACKEND` | `lexicon` / `finbert` | offline vs ProsusAI/finbert |
| `LLM_BACKEND` | `mock` / `vllm` | deterministic templates vs MI300X endpoints |

**Offline-first invariant:** every notebook runs end-to-end with the default offline backends
(`hash` / `lexicon` / `mock` / `memory` / mock data) — no downloads, no network, no GPU. Going
live on the MI300X is purely an `.env` flip; **no node/agent code changes**. Preserve this when
adding features (always provide an offline fallback).

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

## Conventions

- Notebooks are the single source of truth (no generator scripts). A notebook's first code cell
  adds `src/` to `sys.path` by walking up to the repo root, then imports `ir_copilot`.
- The `docs/` MkDocs pages are the design spec — when you change behavior, update the matching
  page and re-run `mkdocs build --strict`.
- Demo data is in `corpus.py` and the `MOCK_SNAPSHOTS` in `facts.py`; `defeatbeta-api` method
  names are in `facts.SPECS`.
- Generated artifacts (`artifacts/`, `data/`, `site/`, models, `.env`) are git-ignored.
