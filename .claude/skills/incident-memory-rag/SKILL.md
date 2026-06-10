---
name: incident-memory-rag
description: >
  How this repo's incident-memory RAG works — Qdrant + bge-small-en-v1.5, the
  ORDER-PRESERVING incident fingerprint, confirmed-only indexing, and the recurring-incident
  retrieval that is the project's headline benchmark advantage. Use whenever the work touches
  `memory/`, `incident_memory`, `IncidentMemoryAgent`, the incident fingerprint, Qdrant
  collections/upsert/search, bge-small / sentence-transformers embeddings for incidents, the
  "learning loop" that indexes a confirmed incident, retrieving similar past incidents, the
  `memory_match_score` / MemoryMatch card, or the memory-ON vs memory-OFF benchmark ablation
  and its strict no-leakage time split. Also trigger when someone asks "why is the wrong
  remediation retrieved", "should we use BGE-M3", or "how do we prove memory helps".
  (For general RAG theory use `rag-implementation`; this skill is the project-specific design.)
---

# Incident-Memory RAG (RCA agent)

Incident memory is the product's **compounding advantage** and the basis of the headline
benchmark: real ops is dominated by *recurring* incidents, so a localizer that remembers
human-confirmed root causes pins them — an edge no stateless RCA method has. It is also the
**learning loop**: every confirmed incident is indexed, so accuracy rises with incidents-seen.

**Deep reference:** [`docs/08-incident-memory-rag.md`](../../../docs/08-incident-memory-rag.md)
(full code) and [`docs/12-benchmark-rcaeval-tsbad.md`](../../../docs/12-benchmark-rcaeval-tsbad.md)
(the memory-uplift benchmark). Working harness:
[`bench/incident_memory.py`](../../../bench/incident_memory.py).

## The three design decisions that matter

### 1. Order-preserving fingerprint (the bug to never reintroduce)

`A→B→C` is a *different* incident from `C→B→A`; embedding them identically retrieves the wrong
remediation. **Join the causal chain unsorted.** Only genuinely set-like fields (towers, log
templates) are sorted for stability.

```python
def build_fingerprint(ordered_chain, fault_hint, log_templates, towers) -> str:
    return (f"chain: {' -> '.join(ordered_chain[:6])}\n"          # ORDERED, never sorted
            f"fault_hint: {fault_hint or ''}\n"
            f"log_templates: {' | '.join(sorted(log_templates[:5]))}\n"   # set-like → sorted
            f"towers: {' '.join(sorted(towers))}")
```

### 2. bge-small-en-v1.5, not BGE-M3

Incident fingerprints are short English strings. [`BAAI/bge-small-en-v1.5`](https://huggingface.co/BAAI/bge-small-en-v1.5)
(133 MB, 384-dim, CPU-fast, MTEB top-5) is right-sized; BGE-M3's multilingual/long-doc
strengths don't apply and add 570 MB of overhead. Use `normalize_embeddings=True` and cosine
distance. Future: `bge-base-en-v1.5` or BGE-M3 only if logs go multilingual.

### 3. Confirmed-only indexing (no poisoning)

Only `reviewer_confirmed=True` incidents are upserted, and retrieval filters on it. Memory
learns only from human-validated truth.

## Qdrant usage

```python
# collection: COSINE, size = 384 (must equal the embedder dim)
client.create_collection(COLLECTION, vectors_config=models.VectorParams(
    size=384, distance=models.Distance.COSINE))

# index on confirm (learning loop)
vec = embed.encode(fingerprint, normalize_embeddings=True)
client.upsert(COLLECTION, points=[models.PointStruct(id=inc.id, vector=vec.tolist(),
    payload={"root_cause_signal": ..., "top_chain": inc.top_chain,   # ordered
             "remediation": ..., "reviewer_confirmed": True, "occurred_at": ...})])

# retrieve at incident time (top similarity = memory_match_score)
hits = client.search(COLLECTION, query_vector=vec.tolist(), limit=3, with_payload=True,
    query_filter=models.Filter(must=[models.FieldCondition(
        key="reviewer_confirmed", match=models.MatchValue(value=True))]))
```

Run Qdrant: `docker run -p 6333:6333 -v "$PWD/qdrant_storage:/qdrant/storage" qdrant/qdrant`
(dashboard at `:6333/dashboard`). Mount a volume or data is lost on restart.

## Proving memory helps (the benchmark)

The claim is an **ablation on a public benchmark**: memory-ON beats memory-OFF (and BARO) on
RCAEval's recurring-fault subset (AC@1/Avg@5). Two integrity rules:

- **Strict no-leakage time split** — seed memory only from *earlier* occurrences; test on later
  ones ([`bench/time_split.py`](../../../bench/time_split.py)). This is what makes the claim
  honest; state it on the slide.
- **`alpha=0` reproduces memory-OFF exactly** — the blend knob isolates the memory
  contribution, so the uplift can't be a confound.

Run: `python bench/run_benchmark.py --synthetic` (smoke) or `--dataset RE2 --data-root ...`
(real). Headline numbers require the real bge-small embedder, never the hashed fallback.

## Pitfalls

| Symptom | Cause / fix |
|---|---|
| Wrong remediation retrieved | Chain got sorted somewhere — keep `build_fingerprint` order-preserving |
| Dim mismatch on upsert | Collection `size` must equal embedder dim (384 for bge-small) |
| Empty results | Filter excludes everything — seeded incidents need `reviewer_confirmed=True` |
| Low similarity scores | Using L2 not cosine, or embeddings not normalised |
| Data lost on restart | Mount `-v ... /qdrant/storage` |
| Memory uplift ≈ 0 on real data | Too few recurring occurrences per group, or fingerprint not capturing the fault signature — inspect retrieved neighbours |
| Suspiciously high benchmark numbers | Leakage — confirm the split seeds only earlier occurrences |
