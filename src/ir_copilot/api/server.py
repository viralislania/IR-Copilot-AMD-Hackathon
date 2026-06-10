"""FastAPI app — every IR-Copilot capability as an HTTP API, plus the CopilotKit AG-UI endpoint.

Run (Python 3.11+ venv):
    PYTHONPATH=src .venv312/bin/python -m uvicorn ir_copilot.api.server:app --reload --port 8088

REST:
    GET  /health
    GET  /api/facts/{ticker}?period=
    GET  /api/sentiment/{ticker}
    GET  /api/competitor/{ticker}
    GET  /api/questions/{ticker}
    GET  /api/draft/{ticker}
    GET  /api/wiki/search?q=&ticker=&k=
    GET  /api/run/{ticker}/stream         (SSE: streams agent updates, pauses at human gate)
    POST /api/run/{ticker}/resume         (resume after human approve/edit)
CopilotKit:
    POST /copilotkit                      (AG-UI: React frontend connects here)
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .. import service
from ..config import settings
from ..graph import build_graph, initial_state

app = FastAPI(title="IR-Copilot API", version="1.0",
              description="Grounded multi-agent Investor-Relations workflow.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# One graph instance with a persistent checkpointer so /stream and /resume share thread state.
_graph = build_graph()


@app.get("/health")
def health():
    return {"status": "ok", "ticker": settings.ticker, "period": settings.period,
            "peers": settings.peers, "data": "mock" if settings.use_mock_data else "live",
            "backends": {"qdrant": settings.qdrant_mode, "embeddings": settings.embedding_backend,
                         "sentiment": settings.sentiment_backend, "llm": settings.llm_backend}}


@app.get("/api/facts/{ticker}")
def facts(ticker: str, period: Optional[str] = None):
    return service.get_facts(ticker.upper(), period)


@app.get("/api/sentiment/{ticker}")
def sentiment(ticker: str):
    return service.get_sentiment(ticker.upper())


@app.get("/api/competitor/{ticker}")
def competitor(ticker: str, period: Optional[str] = None):
    return service.get_competitor(ticker.upper(), period)


@app.get("/api/questions/{ticker}")
def questions(ticker: str, period: Optional[str] = None):
    return {"ticker": ticker.upper(), "questions": service.get_questions(ticker.upper(), period)}


@app.get("/api/draft/{ticker}")
def draft(ticker: str, period: Optional[str] = None):
    return service.get_draft(ticker.upper(), period)


@app.get("/api/wiki/search")
def wiki_search(q: str, ticker: Optional[str] = None, k: int = Query(5, ge=1, le=20)):
    return {"query": q, "results": service.search_wiki(q, ticker.upper() if ticker else None, k)}


# ---- Streaming pipeline with human-in-the-loop ----
class ResumeBody(BaseModel):
    thread_id: str
    decision: str = "approve"          # approve | edit
    edit: Optional[dict] = None


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, default=str)}


@app.get("/api/run/{ticker}/stream")
async def run_stream(ticker: str, period: Optional[str] = None):
    from sse_starlette.sse import EventSourceResponse
    ticker = ticker.upper()
    thread_id = f"{ticker}-{period or settings.period}"
    cfg = {"configurable": {"thread_id": thread_id}}

    def gen():
        for ev in _graph.stream(initial_state(ticker, period), cfg, stream_mode="updates"):
            for node, upd in ev.items():
                msg = upd.get("messages", [("ai", "")])[-1][1] if isinstance(upd, dict) else ""
                yield _sse("node", {"node": node, "message": msg})
        st = _graph.get_state(cfg)
        if st.next == ("hitl",):
            yield _sse("awaiting_human", {"thread_id": thread_id,
                                          "rendered": st.values.get("rendered"),
                                          "verification": st.values["verification"].model_dump()})
        else:
            yield _sse("done", {"thread_id": thread_id})
    return EventSourceResponse(gen())


@app.post("/api/run/{ticker}/resume")
def run_resume(ticker: str, body: ResumeBody):
    from langgraph.types import Command
    cfg = {"configurable": {"thread_id": body.thread_id}}
    update = {"human_feedback": {"decision": body.decision, "edit": body.edit}}
    msgs = []
    for ev in _graph.stream(Command(resume=True, update=update), cfg, stream_mode="updates"):
        for node, upd in ev.items():
            if isinstance(upd, dict) and upd.get("messages"):
                msgs.append({"node": node, "message": upd["messages"][-1][1]})
    st = _graph.get_state(cfg)
    return {"done": st.next == (), "messages": msgs, "rendered": st.values.get("rendered")}


# ---- CopilotKit AG-UI endpoint (React frontend connects here) ----
def _mount_copilotkit() -> bool:
    try:
        from copilotkit import CopilotKitRemoteEndpoint, LangGraphAGUIAgent
        from copilotkit.integrations.fastapi import add_fastapi_endpoint
    except Exception as e:  # pragma: no cover
        print(f"[api] CopilotKit not available ({e}); REST + SSE endpoints still active.")
        return False
    sdk = CopilotKitRemoteEndpoint(agents=[
        LangGraphAGUIAgent(name="ir_copilot",
                           description="Earnings-call IR workflow (script, deck, Q&A).",
                           graph=build_graph())])
    add_fastapi_endpoint(app, sdk, "/copilotkit")
    return True


COPILOTKIT_MOUNTED = _mount_copilotkit()
