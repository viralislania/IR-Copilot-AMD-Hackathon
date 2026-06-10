# Evaluation

How we **prove** each headline claim with a number, not a vibe.

## 1. No hallucinated numbers

- **Method:** an adversarial test set where wrong figures are injected into draft regenerations.
- **Target:** the [numeric verifier](grounding.md) catches **100%** of ungrounded numbers.
- **Report:** precision/recall of flagged numeric tokens.

## 2. No missing numbers (coverage)

- **Method:** a required-metric checklist per period (revenue, EPS, margins, guidance,
  segment/geo revenue...).
- **Target:** every required metric with an available fact appears in the script/cheat-sheet.
- **Report:** coverage % and the list of any flagged gaps.

## 3. Claim grounding

- **Method:** NLI entailment of narrative claims against retrieved [wiki](wiki-ingestion.md)
  evidence.
- **Report:** % of claims with supporting evidence; flagged-claim precision.

## 4. Fine-tuning win ⭐ (the headline)

| Metric | Base (few-shot) | Fine-tuned (zero-shot) |
|---|---|---|
| Question-prediction **recall@10** | baseline | target **↑** |
| Semantic match vs real analyst Q&A | baseline | target **↑** |
| Few-shot examples in prompt | ~6 | **0** |
| Mean input tokens / call | baseline | target **−60–70%** |

- **Held-out split:** companies/quarters unseen in training (strict no-leakage).
- **Report:** base vs fine-tuned side by side on the same held-out set; ship the winner.

## 5. AMD MI300X performance

- **Method:** run all six agents concurrently against the [vLLM node](rocm-vllm.md).
- **Report:** tokens/sec, concurrent-agent latency, GPU utilization (`rocm-smi`), and that 70B
  drafting runs **full-precision, no quantization** on a single MI300X.

## 6. RAG quality (and the embedding fine-tune, if done)

- **Method:** a labeled query set over the wiki, including **financial-jargon queries**
  (non-GAAP, RPO, DSO, segment/geography names, ratio names).
- **Report:** retrieval **hit-rate@5 / nDCG@10** and citation correctness (does the cited span
  actually support the claim).
- **Embedding fine-tune A/B (stretch):** base `bge-base` vs the
  [finance-tuned embedder](finetuning.md#secondary-stretch-fine-tune-the-embedding-model) on the
  same queries / two Qdrant collections; ship the finance-tuned one only if it wins.

## Summary scoreboard (demo slide)

| Claim | Evidence |
|---|---|
| No hallucinated numbers | verifier catch-rate on injected-error set |
| No missing numbers | coverage % |
| Fine-tuning improves accuracy **and** tokens | recall@10 ↑, tokens −60–70% |
| Runs on AMD | MI300X tokens/sec + `rocm-smi`, 70B full-precision |
| Everything grounded | % claims with evidence chips |
