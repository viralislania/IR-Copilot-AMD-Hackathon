"""LangGraph orchestration (docs/orchestration.md).

Six agent nodes + a human-in-the-loop interrupt + a verifier retry loop. Streams node updates.
All agents run offline in mock mode; flip LLM_BACKEND=vllm to use the MI300X models.

State holds only serializable data (pydantic models / lists) so the checkpointer can persist it
across the human interrupt. The FactStore is rebuilt inside nodes; the Qdrant wiki is a
process-level singleton (clients aren't serializable).

    from ir_copilot.graph import build_graph, initial_state
    graph = build_graph()
    for ev in graph.stream(initial_state("NVDA","FY2026Q1"), config): ...
"""
from __future__ import annotations

from typing import Annotated, Any, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from . import corpus
from .config import settings
from .embeddings import get_embedder
from .facts import FactStore, build_fact_store
from .llm import get_chat
from .vectorstore import WikiChunk, WikiStore
from .agents.competitor import compare
from .agents.drafting import draft, render_bundle
from .agents.predictive import predict_questions
from .agents.sentiment import analyze_sentiment
from .agents.verify import verify

MAX_DRAFT_RETRIES = 2

# Process-level wiki cache keyed by ticker set (Qdrant client isn't serializable → not in state).
_WIKI: dict[frozenset, WikiStore] = {}


def _get_wiki(tickers: list[str]) -> WikiStore:
    key = frozenset(t.upper() for t in tickers)
    if key not in _WIKI:
        w = WikiStore(get_embedder())
        w.ensure_collection(recreate=True)
        chunks = corpus.wiki_chunks_for(sorted(key))
        if chunks:
            w.upsert([WikiChunk(chunk_id=str(i), **c) for i, c in enumerate(chunks)])
        _WIKI[key] = w
    return _WIKI[key]


class IRState(TypedDict, total=False):
    ticker: str
    period: str
    facts: list                      # list[FinancialFact]
    peer_facts: dict                 # {ticker: list[FinancialFact]}
    wiki_ready: bool
    sentiment: Any                   # SentimentSnapshot
    peer_comparison: Any             # PeerComparison
    predicted_questions: list        # list[Question]
    draft_bundle: Any                # DraftBundle
    rendered: dict
    verification: Any                # VerifyReport
    draft_attempts: int
    human_feedback: Optional[dict]
    messages: Annotated[list, add_messages]


def initial_state(ticker: str | None = None, period: str | None = None) -> IRState:
    return {"ticker": ticker or settings.ticker, "period": period or settings.period,
            "draft_attempts": 0, "messages": []}


def _store(state: IRState) -> FactStore:
    return FactStore.from_facts(state["ticker"], state["period"], state["facts"])


# ---- nodes ----
def n_extract(state: IRState) -> dict:
    store = build_fact_store(state["ticker"], state["period"], use_mock=settings.use_mock_data)
    peers = {p: build_fact_store(p, state["period"], use_mock=settings.use_mock_data)
             for p in settings.peers}
    return {"facts": store.facts, "peer_facts": {p: ps.facts for p, ps in peers.items()},
            "messages": [("ai", f"Extracted {len(store.facts)} grounded facts; {len(peers)} peers.")]}


def _wiki_tickers(state: IRState) -> list[str]:
    return [state["ticker"], *settings.peers]


def n_wiki(state: IRState) -> dict:
    wiki = _get_wiki(_wiki_tickers(state))
    return {"wiki_ready": True, "messages": [("ai", f"Indexed wiki ({wiki.mode}).")]}


def n_sentiment(state: IRState) -> dict:
    items = corpus.news_items(state["ticker"])
    snap = analyze_sentiment(state["ticker"], items)
    return {"sentiment": snap,
            "messages": [("ai", f"Net sentiment {snap.net_score}; {len(snap.negative_themes)} concerns.")]}


def n_compare(state: IRState) -> dict:
    store = _store(state)
    peers = {p: FactStore.from_facts(p, state["period"], fl) for p, fl in state["peer_facts"].items()}
    pc = compare(store, peers)
    return {"peer_comparison": pc, "messages": [("ai", f"Peer leads={pc.leads} lags={pc.lags}.")]}


def n_predict(state: IRState) -> dict:
    qs = predict_questions(_store(state), state["sentiment"], state["peer_comparison"],
                           wiki=_get_wiki(_wiki_tickers(state)), chat=get_chat("analyst"))
    return {"predicted_questions": qs, "messages": [("ai", f"Predicted {len(qs)} hard questions.")]}


def n_draft(state: IRState) -> dict:
    store = _store(state)
    bundle = draft(store, state["sentiment"], state["peer_comparison"],
                   state["predicted_questions"], chat=get_chat("drafting"))
    rendered = render_bundle(bundle, store)
    n = state.get("draft_attempts", 0) + 1
    return {"draft_bundle": bundle, "rendered": rendered, "draft_attempts": n,
            "messages": [("ai", f"Drafted script/deck/Q&A (attempt {n}).")]}


def n_verify(state: IRState) -> dict:
    rep = verify(state["rendered"], _store(state))
    msg = "Verification passed." if rep.passed else \
        f"Verification FAILED: numeric={rep.numeric_violations} missing={rep.coverage_missing}"
    return {"verification": rep, "messages": [("ai", msg)]}


def n_hitl(state: IRState) -> dict:
    fb = state.get("human_feedback") or {"decision": "approve"}
    return {"messages": [("ai", f"Human decision: {fb.get('decision')}.")]}


def n_finalize(state: IRState) -> dict:
    # Learning-loop hook: write approved Q&A back to the wiki (docs/orchestration.md).
    return {"messages": [("ai", "Finalized artifacts: script, deck outline, Q&A cheat sheet.")]}


def _after_verify(state: IRState) -> str:
    if state["verification"].passed:
        return "hitl"
    if state.get("draft_attempts", 0) >= MAX_DRAFT_RETRIES:
        return "hitl"           # escalate to human rather than loop forever
    return "draft"


def build_graph(checkpointer=None, with_interrupt: bool = True):
    g = StateGraph(IRState)
    for name, fn in [("extract", n_extract), ("wiki", n_wiki), ("sentiment", n_sentiment),
                     ("compare", n_compare), ("predict", n_predict), ("draft", n_draft),
                     ("verify", n_verify), ("hitl", n_hitl), ("finalize", n_finalize)]:
        g.add_node(name, fn)

    g.set_entry_point("extract")
    g.add_edge("extract", "wiki")
    g.add_edge("wiki", "sentiment")
    g.add_edge("sentiment", "compare")
    g.add_edge("compare", "predict")
    g.add_edge("predict", "draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", _after_verify, {"draft": "draft", "hitl": "hitl"})
    g.add_edge("hitl", "finalize")
    g.add_edge("finalize", END)

    kwargs: dict = {"checkpointer": checkpointer or MemorySaver()}
    if with_interrupt:
        kwargs["interrupt_before"] = ["hitl"]
    return g.compile(**kwargs)
