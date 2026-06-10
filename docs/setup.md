# Running these docs

This documentation is a **MkDocs (Material)** site.

## Install

```bash
pip install mkdocs-material
```

`mkdocs-material` pulls in `mkdocs` and the `pymdownx` extensions used here (admonitions,
tabs, superfences with Mermaid, code copy).

## Live preview

```bash
# from the repo root (where mkdocs.yml lives)
mkdocs serve
# open http://127.0.0.1:8000
```

The site auto-reloads as you edit files in `docs/`.

## Build static site

```bash
mkdocs build          # outputs to ./site
```

## Deploy (optional)

```bash
mkdocs gh-deploy      # publishes ./site to the gh-pages branch
```

## Mermaid diagrams

Diagrams in these docs use fenced ```mermaid blocks, enabled via
`pymdownx.superfences` in `mkdocs.yml`. Material renders them client-side — no extra plugin
needed for local preview. (If diagrams don't render on a very old Material version, add the
`mermaid2` plugin.)

## Structure

```
amdhackathonfin/
├── mkdocs.yml          # site config + nav
├── PLAN.md             # single-file summary (superseded in detail by docs/)
├── requirements.txt        # core deps (cross-platform)
├── requirements-gpu.txt    # MI300X/ROCm-only deps (vLLM, unsloth, whisper)
├── .env.example            # config template ( .env is git-ignored )
├── src/ir_copilot/         # the implementation package
│   ├── config.py           #   settings from .env
│   ├── facts.py            #   Financial Fact Store + grounding helpers
│   ├── embeddings.py       #   hash | sentence-transformers | vllm
│   ├── vectorstore.py      #   Qdrant wiki (memory | docker | local)
│   ├── llm.py              #   mock | vllm chat clients
│   ├── corpus.py           #   demo transcripts/news/social
│   ├── graph.py            #   LangGraph orchestration + HITL interrupt
│   └── agents/             #   sentiment, competitor, predictive, drafting, verify
├── notebooks/              # step-by-step, runnable offline (mock backends)
│   ├── 01_data_extraction_fact_store.ipynb
│   ├── 02_wiki_ingestion_qdrant.ipynb
│   ├── 03_market_sentiment.ipynb
│   ├── 04_competitor_comparison.ipynb
│   ├── 05_predictive_analyst.ipynb
│   ├── 06_drafting_and_grounding.ipynb
│   ├── 07_langgraph_orchestration.ipynb
│   └── 08_finetuning_unsloth.ipynb   # ⭐ GPU-only (recipe + eval)
└── docs/
    ├── index.md
    ├── architecture.md
    ├── agents.md
    ├── data-sources.md
    ├── wiki-ingestion.md
    ├── grounding.md
    ├── sentiment.md
    ├── competitor.md
    ├── finetuning.md      ⭐ critical feature
    ├── rocm-vllm.md       ⭐ critical platform
    ├── orchestration.md
    ├── ui.md
    ├── roadmap.md
    ├── evaluation.md
    ├── demo.md
    └── setup.md
```

When we move to implementation, code lands under `backend/`, `finetune/`, and `frontend/`
(CopilotKit) / `flutter_app/` (optional), mirroring these docs.
