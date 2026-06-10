# Demo Script (4 minutes)

A tight, reproducible run. Everything (facts, embeddings, a recorded transcript) is cached so
the demo never depends on the network.

## Beat-by-beat

1. **Setup (0:00).** Enter ticker **NVDA** + quarter. `useCoAgent` starts the LangGraph run.
2. **Financial Snapshot (0:20).** Metric cards fill as `facts` stream in via state updates —
   point out each number carries a source ([data](data-sources.md), [grounding](grounding.md)).
3. **Market Sentiment (0:50).** Net-sentiment gauge + "topics investors are angry about" theme
   cards, each with source headlines ([sentiment](sentiment.md)).
4. **Competitor (1:15).** Comparison table vs AMD/INTC/AVGO; highlight a **lag** (e.g. a margin
   gap) — note it will resurface as a predicted question ([competitor](competitor.md)).
5. **Predicted Q&A (1:40).** Ranked hard questions from the **fine-tuned** Predictive Analyst.
   Cut to the **headline slide**: recall@10 ↑ and prompt tokens −60–70% vs base
   ([fine-tuning](finetuning.md)).
6. **Draft Script (2:20).** Streams sentence-by-sentence, each with an **evidence chip**
   `[F-0012]` ([UI](ui.md)).
7. **No-hallucination proof (2:50).** Inject a wrong number into a regenerate prompt → the
   **Grounding Verifier blocks it** and loops back ([grounding](grounding.md)).
8. **Human-in-the-loop (3:15).** Reviewer **edits one line and approves** → graph resumes →
   final **script + deck outline + Q&A cheat sheet** ([orchestration](orchestration.md)).
9. **AMD proof (3:45).** Cut to **`rocm-smi`** on the MI300X — all six agents (incl. 70B
   drafting, full-precision, and the hot-swapped LoRA) ran on one AMD node
   ([MI300X](rocm-vllm.md)).

## What each beat proves to judges

| Beat | Requirement proven |
|---|---|
| 2 | accurate financials from defeatbeta-api, grounded |
| 3 | news + social sentiment |
| 4 | competitor comparison before drafting |
| 5 | **fine-tuning** (accuracy + token win) — the critical feature |
| 6 | streaming + evidence everywhere |
| 7 | **no hallucinated numbers** |
| 8 | **human-in-the-loop** + LangGraph interrupt/resume |
| 9 | **AMD ROCm + vLLM on MI300X** — the critical platform |

## Backup plan

If anything upstream is flaky, the cached fact store + embeddings + recorded transcript carry
the full run. The base model path is always live, so a fine-tune hiccup never blocks the demo
([roadmap](roadmap.md)).
