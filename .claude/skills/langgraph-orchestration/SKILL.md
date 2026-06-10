---
name: langgraph-orchestration
description: >
  How to build and debug the RCA agent's LangGraph state machine in this repo — nodes,
  conditional edges, the human-review interrupt, the checkpointer, and SSE streaming. Use
  this whenever the work touches `graph/`, `agents/` nodes, `ObservabilityState`,
  `build_observability_graph`, `StateGraph`, `add_node`/`add_edge`/`add_conditional_edges`,
  `interrupt_before`, `MemorySaver`, `graph.stream`, resuming a paused graph, the
  human-in-the-loop review step, or the learning loop that writes a confirmed incident back
  to memory. Also trigger when someone asks "how does the pipeline flow", "why does resume
  re-run nodes", "how do I add an agent step", or wires a new node into the orchestrator.
---

# LangGraph Orchestration (RCA agent)

The pipeline is a stateful, branching, interruptible workflow. Plain function chaining can't
express the two things this product needs: a **confidence gate** (auto-close vs human review)
and a **durable interrupt** (pause for a human, resume without re-running prior nodes).
LangGraph gives both, plus a typed shared state and a checkpointer.

**Deep reference:** [`docs/03-orchestration-langgraph.md`](../../../docs/03-orchestration-langgraph.md)
(full code) and [`docs/10-api-agui-sse.md`](../../../docs/10-api-agui-sse.md) (streaming to the UI).
Read those for the complete graph; this skill is the working playbook + pitfalls.

## The pipeline

```
anomaly_detect → log_triage → hypothesis_rank → incident_memory
   → rca_narrative → grounding_verify → [confidence gate] → human_review → END
```

`route_by_confidence` auto-closes only when `rca_confidence >= 0.80 AND grounding_passed`;
everything else routes to `human_review`.

## Core patterns (get these right)

**A node is `state -> partial_state`.** Return ONLY the keys you change — LangGraph merges
them into `ObservabilityState`. Returning a fresh full dict or typo'ing a key silently breaks
downstream reads (TypedDict isn't enforced at runtime).

```python
def hypothesis_rank_node(state: ObservabilityState) -> dict:
    ranked = HypothesisRanker().rank(...)
    return {"ranked_hypotheses": [h.model_dump() for h in ranked.hypotheses],
            "suggested_root_signal": ranked.top,
            "ranking_confidence": ranked.confidence}
```

**Compile with a checkpointer + interrupt.** The checkpointer is what makes resume cheap.

```python
g.add_conditional_edges("grounding_verify", route_by_confidence,
                        {"review": "human_review", "auto_close": END})
return g.compile(checkpointer=MemorySaver(), interrupt_before=["human_review"])
```

**Run, pause, resume — same `thread_id`.** The `thread_id` is how the checkpointer finds the
paused state. Resume by calling `stream(None, cfg)` after writing the reviewer's action.

```python
cfg = {"configurable": {"thread_id": incident_id}}
for ev in graph.stream(initial_state, cfg, stream_mode="updates"):
    emit_sse(ev)                      # one event per node → progressive UI
# ... reviewer clicks Confirm ...
graph.update_state(cfg, {"reviewer_action": "CONFIRM"})
for ev in graph.stream(None, cfg, stream_mode="updates"):   # None = resume
    emit_sse(ev)
# human_review_node writes the confirmed incident to Qdrant — the learning loop
```

## Adding a new node

1. Define `def my_node(state) -> dict:` returning only its new keys.
2. Add the keys to `ObservabilityState` (`graph/state.py`).
3. `g.add_node("my_node", my_node)` and wire edges (or a conditional edge with a routing map).
4. If it should pause for a human, add its name to `interrupt_before`.
5. Add a per-node unit test (`node(fixed_state)` → assert returned partial). Nodes are pure.

## Streaming for the UI

`stream_mode="updates"` emits one event per node completion — that drives the progressive
genui reveal. Map node name → SSE event per the contract in
[`docs/10-api-agui-sse.md`](../../../docs/10-api-agui-sse.md).

## Version pin (important)

Pin `langgraph>=0.2,<0.3` for this project and use `interrupt_before`. The `interrupt()`
function and resume ergonomics changed in 0.3 — check the
[persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/) and
[HITL](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/) guides for the
pinned version before changing interrupt code.

## Pitfalls

| Symptom | Cause / fix |
|---|---|
| Resume re-runs earlier nodes | Missing/mismatched `thread_id`, or no checkpointer passed to `compile()` |
| Interrupt never fires | Name in `interrupt_before` doesn't match an `add_node` name |
| Downstream `KeyError` | A node returned a full dict instead of a partial update, or typo'd a key |
| Conditional edge `KeyError` | Router returned a label not in the routing map |
| Stream emits nothing | Wrong `stream_mode` — use `"updates"` for per-node events |
| State not JSON-serialisable | Keep `ObservabilityState` flat dicts/lists; the checkpointer and SSE both serialise it |

## Guardrails specific to this product

- **The ranker decides the suspect; the LLM only explains.** Don't let `rca_narrative`
  override `suggested_root_signal`.
- **Only confident + grounded RCAs auto-close.** Never weaken `route_by_confidence` to skip
  human review on ungrounded output.
- **Keep two LLM nodes.** `log_triage` and `rca_narrative` are the only LLM calls by design
  (token budget — [`docs/13`](../../../docs/13-llm-and-token-budget.md)). Justify any third.
