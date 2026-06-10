# 4-Day Roadmap

The build is sequenced so the system always works end-to-end with the **base model**, and
[fine-tuning](finetuning.md) — the most critical feature — is slotted in as availability allows
and hot-swapped the moment it beats the baseline.

## Day 1 — Platform + Data

| Task | Done when |
|---|---|
| Stand up [vLLM on MI300X](rocm-vllm.md): drafting (70B), reasoning (8B), BGE embeddings | OpenAI calls + embeddings return; `rocm-smi` shows GPU busy |
| [defeatbeta-api](data-sources.md) → [Financial Fact Store](grounding.md) with provenance | all metrics present for demo ticker; gaps recorded |
| DuckDB cache of demo ticker(s) | demo runs offline |
| **Kick off fine-tune data prep** ([Unsloth](finetuning.md)) | (context → analyst Q&A) pairs built from HF/Kaggle |

## Day 2 — Wiki + Agents

| Task | Done when |
|---|---|
| [Qdrant wiki](wiki-ingestion.md) ingest (API + at least one custom PDF/audio source) | reranked, cited retrieval works |
| LangGraph nodes 1–5 wired with streaming | end-to-end draft generated from base model |
| [Sentiment](sentiment.md) (news + FinBERT) + [Competitor](competitor.md) agents | snapshot + comparison in state |
| **Fine-tune run #1** on MI300X | LoRA adapter trains; baseline eval recorded |

## Day 3 — Grounding + UI + Fine-tune

| Task | Done when |
|---|---|
| [Grounding Verifier](grounding.md): numeric + coverage + NLI | injected wrong number is caught & blocked |
| [CopilotKit UI](ui.md): all screens + streamed state | live dashboard fills as agents run |
| HITL interrupt + resume (approve/edit) | reviewer edits a paragraph; graph resumes |
| **Fine-tune eval + hot-swap** via `--enable-lora` | recall@10 ↑ and prompt tokens ↓ vs base → adapter shipped |

## Day 4 — Prove + Polish + Demo

| Task | Done when |
|---|---|
| [Evaluation](evaluation.md): no-hallucination, coverage, fine-tune win, ROCm perf | numbers captured for slides |
| Learning loop (approved Q&A → wiki) | next run retrieves the precedent |
| **(Stretch) [finance-tuned embedding model](finetuning.md#secondary-stretch-fine-tune-the-embedding-model)** | only if core + primary fine-tune solid; A/B hit-rate vs base; drop-in swap |
| (Optional) Flutter GenUI demo | renders streamed cards |
| Dry-run the [demo](demo.md) twice; cache everything | reproducible 4-minute run |

## Critical-feature guard rails

- Fine-tuning is **decoupled**: the base model path is always live, so a fine-tune delay never
  blocks the demo.
- The adapter is **additive + hot-swappable** (`--enable-lora`) — ship whichever wins on the
  held-out set.
- If Unsloth's ROCm kernels lag, fall back to **TRL/PEFT QLoRA** with identical data, LoRA
  config, and serving path (see [Fine-tuning](finetuning.md)).
