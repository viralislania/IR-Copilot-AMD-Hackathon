# Fine-tuning (Unsloth) ⭐

!!! tip "This is the most critical feature"
    Fine-tuning is the headline of the project. It is **scheduled flexibly across the 4-day
    hackathon** (see the [Roadmap](roadmap.md)) so the rest of the system always works with the
    base model, and the fine-tuned adapter is hot-swapped in the moment it beats the baseline.

There are **two fine-tunes**, in priority order:

| Priority | Target | Wins | Section |
|---|---|---|---|
| **Primary (critical)** | Predictive-Analyst LLM (DeepSeek/Llama + LoRA) | question recall ↑, prompt tokens ↓ | below |
| **Secondary (stretch, time-permitting)** | Embedding model (BGE) for financial jargon | retrieval hit-rate ↑ across the whole RAG pipeline | [below](#secondary-stretch-fine-tune-the-embedding-model) |

## Use case: the Predictive Analyst Agent

Predicting the **hardest analyst questions** is the highest-value, most learnable skill in the
pipeline — and the clearest place to show a measurable fine-tuning win.

### Why fine-tune instead of prompt

A base model needs many few-shot examples of *(transcript + financials → analyst questions)*
stuffed into the prompt to predict well. That is:

- **expensive in tokens** (few-shot blocks dominate the context), and
- **context-diluting** (less room for the actual financials and evidence).

Fine-tuning moves the skill **into the weights**, giving **higher question recall** with a
**much smaller prompt**.

## Recipe (Unsloth QLoRA)

- **Base model:** `deepseek-ai/DeepSeek-R1-Distill-Llama-8B` (reasoning-strong) — or
  `meta-llama/Llama-3.1-8B-Instruct`.
- **Data:** *(prepared remarks + financial snapshot)* → *(actual analyst Q&A turns)* pairs
  mined from earnings transcripts:
  HF `lamini/earnings-calls-qa`, HF `jlh-ibm/earnings_call`, Kaggle Motley-Fool transcripts.
  We split the analyst-question turns as the supervision target.
- **Method:** Unsloth 4-bit QLoRA, LoRA `r=16`, on the [MI300X](rocm-vllm.md).
- **Serving:** export the LoRA adapter; serve with vLLM `--enable-lora` (no separate full
  model needed).

```python
from unsloth import FastLanguageModel

model, tok = FastLanguageModel.from_pretrained(
    "deepseek-ai/DeepSeek-R1-Distill-Llama-8B",
    max_seq_length=8192, load_in_4bit=True,
)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16,
    target_modules=["q_proj","k_proj","v_proj","o_proj",
                    "gate_proj","up_proj","down_proj"],
)
# SFTTrainer on (context → analyst_questions) pairs ...
model.save_pretrained("lora_qpredict")   # served by vLLM --enable-lora
```

!!! note "Unsloth on ROCm"
    Unsloth's primary target is CUDA. On the MI300X we (a) run QLoRA via the ROCm PyTorch +
    bitsandbytes-rocm path where supported, or (b) fall back to **TRL/PEFT QLoRA** with the
    same dataset and LoRA config if Unsloth's kernels aren't available on ROCm in time. Either
    way the *adapter format and the vLLM `--enable-lora` serving path are identical*, so the
    rest of the system is unaffected. This is why fine-tuning is decoupled and scheduled by
    availability.

## The win we demo (the headline slide)

| Axis | Base (few-shot) | Fine-tuned (zero-shot) |
|---|---|---|
| Question prediction **recall@10** | baseline | **↑** vs base on held-out real Q&A |
| Few-shot examples in prompt | ~6 | **0** |
| Prompt tokens / call | baseline | **~60–70% smaller** |
| Latency / cost on MI300X | baseline | **lower** (fewer input tokens) |

Two independent wins from one adapter:

1. **Accuracy** — higher recall of the questions analysts actually asked (semantic-match /
   overlap against held-out transcripts).
2. **Token & context optimization** — few-shot examples drop to zero, cutting prompt size
   dramatically while freeing context for grounded financials.

## Evaluation protocol

- **Held-out split:** companies/quarters never seen in training.
- **Metric:** recall@k and semantic-match (embedding similarity) of predicted vs actual
  analyst questions; report base vs fine-tuned side by side.
- **Token bench:** mean input tokens/call at equal-or-better recall.

Details and targets in [Evaluation](evaluation.md). Because the adapter is additive and
hot-swappable, **we ship whichever model wins on the held-out set** — the base remains the safe
default until then.

---

## Secondary (stretch): fine-tune the embedding model

!!! note "Time-permitting"
    Done only if the primary fine-tune and the core pipeline are solid. It is **low-risk** —
    a better embedding model is a drop-in replacement at the [embedding step](wiki-ingestion.md)
    and needs no app changes.

### Why

The stock `BAAI/bge-base-en-v1.5` is general-purpose. Financial text is dense with jargon a
general model embeds poorly: tickers, GAAP vs **non-GAAP**, "TTM", "deferred revenue",
"RPO", "DSO", "sequential vs YoY", ratio names (ROIC/WACC/PEG), and segment/geography labels.
A **domain-tuned embedder** pulls the right transcript/filing passages for these terms, which
lifts **every RAG-dependent step at once** — [Predictive Analyst](agents.md) retrieval,
evidence chips, and [claim grounding](grounding.md).

### Recipe (sentence-transformers contrastive fine-tune)

- **Base:** `BAAI/bge-base-en-v1.5` (keep the same dim → drop-in).
- **Data — (query, positive passage) pairs** mined from our existing corpora:
    - analyst question → the management answer span that addressed it (from transcripts),
    - financial-term query → the filing/transcript sentence defining or reporting it,
    - HF `financial_phrasebank`, `jlh-ibm/earnings_call`, Kaggle Motley-Fool transcripts.
- **Hard negatives:** mine with the base model (similar-but-wrong passages, e.g. same metric
  for a *different* quarter/peer) so the model learns fine financial distinctions.
- **Loss:** `MultipleNegativesRankingLoss` (in-batch negatives) — standard, data-efficient.
- **Train on MI300X**, re-embed the [wiki](wiki-ingestion.md) into a new Qdrant collection,
  A/B against the base embedder.

```python
from sentence_transformers import SentenceTransformer, losses, InputExample
from torch.utils.data import DataLoader

model = SentenceTransformer("BAAI/bge-base-en-v1.5")   # runs on ROCm
train = [InputExample(texts=[q, pos]) for q, pos in finance_pairs]   # + hard negatives
loader = DataLoader(train, shuffle=True, batch_size=64)
model.fit(train_objectives=[(loader, losses.MultipleNegativesRankingLoss(model))],
          epochs=2, warmup_steps=100)
model.save("bge-finance")     # serve via vLLM --task embed, or sentence-transformers
```

### Win we'd demo

| Metric | Base BGE | Finance-tuned BGE |
|---|---|---|
| Retrieval **hit-rate@5** on a labeled financial-query set | baseline | target **↑** |
| Jargon queries (non-GAAP, RPO, segment names) correctly retrieved | baseline | target **↑** |
| nDCG@10 on the RAG eval set | baseline | target **↑** |

A/B is clean: two Qdrant collections, same queries, compare hit-rate / nDCG
([Evaluation](evaluation.md)). Ship the finance-tuned embedder only if it beats base.
