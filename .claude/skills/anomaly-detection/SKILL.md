---
name: anomaly-detection
description: >
  How this repo detects time-series anomalies for the RCA agent — MODEL-LED detection
  (Anomaly Transformer decider + IsolationForest pre-filter, thresholds only as a floor), the
  spike-vs-fault / false-positive-vs-true-positive control (model score + persistence +
  propagation), and HONEST evaluation with VUS-PR on TSB-AD instead of inflated
  point-adjusted F1. Use whenever the work touches `detection/`, `anomaly_detect`,
  `TowerAnomalyDetector`, `IsolationForest`, Anomaly Transformer, `AnomalyEvent`, metric-window scoring,
  the persistence/debounce gate, or evaluating a detector. Also trigger when someone asks
  "should detection be model-based or threshold-based", "how do we tell a one-off spike from
  a real fault", "why is it a false positive / true positive", reports "the detector flags
  everything / nothing", mentions point-adjustment / PA-F1 / VUS-PR / TSB-AD, or hits the
  Anomaly-Transformer-on-ROCm question, or whether to use MAAT (it's a FUTURE upgrade).
---

# Anomaly Detection (two-stage, honestly evaluated)

Detection must be both **fast** (runs continuously, cheap) and **precise** (no false alarms).
One model can't be both, so the design is two stages, and — just as important — it is
**evaluated honestly**, which is itself a differentiator (most papers overclaim).

**Deep reference:** [`docs/06-anomaly-detection.md`](../../../docs/06-anomaly-detection.md)
(full code + the Anomaly-Transformer-on-ROCm rationale) and
[`docs/12-benchmark-rcaeval-tsbad.md`](../../../docs/12-benchmark-rcaeval-tsbad.md) (TSB-AD).

## Model-led, not threshold-led

A fixed threshold fires on *any* excursion and cannot tell a one-off spike from a real fault.
Detection is therefore **model-led**, in three roles by authority:

- **Anomaly Transformer — the decider** (ICLR'22,
  [arXiv:2110.02642](https://arxiv.org/abs/2110.02642), on the AMD GPU): a temporal
  association-discrepancy scorer. **Pure attention, no custom CUDA kernels → runs cleanly on
  ROCm** (the reason we chose it over Mamba-based MAAT). Its score (gated by persistence) decides.
- **IsolationForest — fast pre-filter** (scikit-learn, CPU, no training): cheaply decides which
  windows are worth scoring with the transformer, so it doesn't run every tick. A filter, not the arbiter.
- **Fixed thresholds — a floor only**: for unambiguous hard failures (e.g. `5xx > 0`). Never
  the primary signal.

## Spike vs fault — the false-positive control (the point of this skill)

A real fault is **model score × persistence × propagation** — all three. An FP is anything
missing one:

| | True fault | Transient spike (FP) |
|---|---|---|
| AT score high | yes | may blip — not enough alone |
| **Persistence** (sustained ≥ debounce, ~10–15s) | yes | recovers in 1–2 samples |
| **Propagation** (cross-tower chain in the ranker) | yes | isolated, no downstream |

- TP example (GPU): KV-cache saturation sustained, queue grows, p99/5xx rise.
- TP example (network): retransmits/ingress latency sustained, p99/5xx rise, **queue normal**.
- FP examples: batch-boundary VRAM blip; a cold-start p99 outlier; a momentary netem burst you
  clear within the debounce; a GC/log-flush tick. High instant value, no persistence/propagation.

Persistence is local (a debounce run-length check in the detector); propagation is global
(the ranker only forms a chain for signals that fired across towers — [doc 07](../../../docs/07-hypothesis-ranking.md)).
Both must hold for a HIGH-confidence fault.

```python
def is_sustained(scores, threshold, min_samples=10):   # persistence gate
    run = 0
    for s in scores:
        run = run + 1 if s >= threshold else 0
        if run >= min_samples: return True
    return False
```

## Why Anomaly Transformer (and not MAAT) on ROCm

The **Anomaly Transformer** is pure attention — a vanilla PyTorch transformer with **no custom
CUDA kernels** — so it builds and runs on **ROCm out of the box** and can score *live* on the
AMD GPU. That is why it is the POC Stage-2 model.

**MAAT** (Mamba Adaptive Anomaly Transformer, arXiv:2502.07858) is a stronger model on paper,
but its Mamba kernels (`mamba-ssm`, `causal-conv1d`) are **CUDA-specific and don't build cleanly
on ROCm**. It's a **[FUTURE] upgrade** — adopt it only once those kernels (or a pure-PyTorch
selective-scan) work on ROCm, keeping the `score(window) -> float` interface so it's a drop-in.
Under PyTorch-ROCm the device is still spelled `"cuda"` (HIP presents as the `cuda` device).

## Evaluation — VUS-PR, never point-adjusted F1 (this is the credibility flex)

Most TSAD papers report **point-adjusted (PA) F1**. Kim et al.
([AAAI'22, arXiv:2109.05257](https://arxiv.org/abs/2109.05257)) proved PA is so permissive a
**random** score can look "state-of-the-art." So:

- Evaluate on **[TSB-AD](https://github.com/TheDatumOrg/TSB-AD)** (NeurIPS'24) using **VUS-PR**,
  the measure that benchmark validated as most reliable.
- Report the **Anomaly Transformer's VUS-PR** vs a simple baseline. **Never headline PA-F1.**
- Expect VUS-PR to look lower than papers' F1 — that's the honest number, and saying so is the
  point.

```bash
pip install TSB-AD     # run the Anomaly Transformer through it, report VUS-PR — one slide
```

## Output contract (`AnomalyEvent`)

Carry both stage scores and a precedence timestamp the ranker needs:

```python
class AnomalyEvent(BaseModel):
    tower: Literal["gpu", "network", "app"]   # three POC towers (doc 07 topology)
    signal_id: str                  # "gpu.vram_used_pct", "net.tcp_retransmit_rate", ...
    value: float; threshold: float
    if_score: float                 # IsolationForest pre-filter
    model_score: float | None        # Anomaly Transformer decider (None if pre-filter rejected)
    sustained: bool                 # persistence gate passed
    confidence: Literal["LOW","MEDIUM","HIGH"]   # HIGH needs model + sustained (+ propagation via ranker)
    timestamp: str; timestamp_epoch: float   # epoch → precedence in the ranker
    raw_metric_window: list[float]  # keep SHORT — summarise before any LLM prompt (docs/13)
```

## Future alternatives

[TimesNet](https://arxiv.org/abs/2211.14730) (if the Anomaly Transformer is unstable),
[AnomalyBERT](https://arxiv.org/abs/2305.04468), or plain z-score/EWMA thresholds (already in
Stage 1's rule layer — a no-ML demo fallback).

## Pitfalls

| Symptom | Cause / fix |
|---|---|
| `mamba-ssm` won't install on ROCm | Use the pure-PyTorch path or fall back to Anomaly Transformer |
| IForest flags everything | Baseline fit on already-anomalous data — refit on a clean pre-fault window; lower `contamination` (0.01–0.05) |
| IForest flags nothing | Signals on different scales — standardise per signal before `fit`; window too short |
| AT score not discriminative | Window length ≠ training `win_size`; align it; match the training normalisation |
| "Our F1 is lower than the paper's" | They used point-adjustment. Your VUS-PR is the honest number — keep it. |

## Guardrails

- Don't replace the deterministic detector with an LLM — it's slower, costlier, less reliable,
  and would break replay. Detection stays numeric.
- Keep `raw_metric_window` short and summarise (mean/peak/delta/changepoint) before feeding any
  window into an LLM prompt — raw arrays waste tokens ([`docs/13`](../../../docs/13-llm-and-token-budget.md)).
