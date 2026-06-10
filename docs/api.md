# HTTP API (FastAPI + CopilotKit)

Every IR-Copilot capability is exposed over HTTP by `api/server.py`,
which wraps the service layer (also callable directly from Python
and the notebooks). The **CopilotKit** frontend connects to the same app.

## Run

```bash
# offline (cached real data): Python 3.9+
PYTHONPATH=src python3 -m uvicorn ir_copilot.api.server:app --port 8088
# live (defeatbeta-api): Python 3.11+ venv, USE_MOCK_DATA=false
PYTHONPATH=src .venv312/bin/python -m uvicorn ir_copilot.api.server:app --reload --port 8088
```

## REST endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | status + active backends |
| GET | `/api/facts/{ticker}?period=` | Financial Fact Store (grounded, with `source`/`source_url`) |
| GET | `/api/sentiment/{ticker}` | net score + themes with cited sources (FinBERT) |
| GET | `/api/competitor/{ticker}` | peer comparison, `leads`/`lags`, grounded `fact_ids` |
| GET | `/api/questions/{ticker}` | predicted hard questions + evidence (real transcript URLs) |
| GET | `/api/draft/{ticker}` | rendered script + deck + Q&A + verification report |
| GET | `/api/wiki/search?q=&ticker=&k=` | cited transcript passages |
| GET | `/api/run/{ticker}/stream` | **SSE** stream of agent updates, pauses at the human gate |
| POST | `/api/run/{ticker}/resume` | resume after human approve/edit |

```bash
curl -s http://127.0.0.1:8088/api/facts/NVDA | jq '.facts[0]'
# { "fact_id":"F-0001","metric":"ttm_eps","value":6.5299,"unit":"USD",
#   "source":"defeatbeta-api:ttm_eps","source_url":"https://huggingface.co/datasets/defeatbeta/...", ... }

curl -N http://127.0.0.1:8088/api/run/NVDA/stream      # streams node updates, then awaiting_human
curl -X POST http://127.0.0.1:8088/api/run/NVDA/resume \
     -H 'Content-Type: application/json' \
     -d '{"thread_id":"NVDA-FY2026Q2","decision":"approve"}'
```

The SSE stream emits `event: node` per agent step, then `event: awaiting_human` carrying the
**rendered draft + verification** when the graph hits the [interrupt](orchestration.md). The UI
shows it for approval; `resume` continues to `finalize`.

## CopilotKit AG-UI endpoint

Mounted at `POST /copilotkit` via the `copilotkit` SDK:

```python
from copilotkit import CopilotKitRemoteEndpoint, LangGraphAGUIAgent
from copilotkit.integrations.fastapi import add_fastapi_endpoint

sdk = CopilotKitRemoteEndpoint(agents=[
    LangGraphAGUIAgent(name="ir_copilot",
                       description="Earnings-call IR workflow (script, deck, Q&A).",
                       graph=build_graph())])
add_fastapi_endpoint(app, sdk, "/copilotkit")
```

A CopilotKit React app sets its runtime URL to `/copilotkit` and drives the same LangGraph agent
over AG-UI (`useCoAgent`, `useCoAgentStateRender`, `useLangGraphInterrupt`). See [UI](ui.md). If
the `copilotkit` package isn't installed, the REST + SSE endpoints still serve the full workflow.

## Service layer (programmatic)

```python
from ir_copilot import service
service.get_facts("NVDA")          # dict
service.get_sentiment("NVDA")      # SentimentSnapshot
service.get_competitor("NVDA")     # PeerComparison
service.get_questions("NVDA")      # list[Question]
service.get_draft("NVDA")          # rendered bundle + verification
service.search_wiki("gross margin", ticker="NVDA", k=5)
```
