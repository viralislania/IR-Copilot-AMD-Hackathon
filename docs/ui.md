# UI — CopilotKit (primary) + Flutter GenUI (optional)

The UI streams live agent state and owns the **human approval gate**. The **primary** front-end
is **CopilotKit CoAgents** (native Python-LangGraph integration); a **Flutter GenUI** app is an
optional alternative transport.

## Primary: CopilotKit CoAgents (AG-UI)

CopilotKit connects a React/Next.js UI to the Python LangGraph agent over the **AG-UI
protocol**, with real-time state sync and built-in human-in-the-loop.

### Backend (Python)

```python
from copilotkit import CopilotKitRemoteEndpoint, LangGraphAGUIAgent
from copilotkit.integrations.fastapi import add_fastapi_endpoint

sdk = CopilotKitRemoteEndpoint(agents=[
    LangGraphAGUIAgent(name="ir_copilot", description="Earnings-call IR workflow",
                       graph=build_graph()),
])
add_fastapi_endpoint(app, sdk, "/copilotkit")
```

Packages: `pip install copilotkit langgraph`. This is implemented in
`api/server.py` — see the [HTTP API](api.md) page for the full
endpoint list (REST + SSE) that the frontend also uses.

### Frontend (React)

```tsx
// Stream the whole IR run state and render progressively
const { state } = useCoAgent<IRState>({ name: "ir_copilot" });

// Render agent progress as custom components (financial snapshot, sentiment, etc.)
useCoAgentStateRender({
  name: "ir_copilot",
  render: ({ state }) => <IRDashboard state={state} />,
});

// Human-in-the-loop: render the draft + Approve/Edit/Regenerate at the interrupt
useLangGraphInterrupt({
  render: ({ event, resolve }) => (
    <DraftReview draft={event.value.draft}
                 onApprove={() => resolve({ decision: "approve" })}
                 onEdit={(edit) => resolve({ decision: "edit", edit })} />
  ),
});
```

Packages: `@copilotkit/react-core`, `@copilotkit/react-ui`.

| Need | CopilotKit hook |
|---|---|
| Start run + read streamed state | `useCoAgent` |
| Render live agent progress | `useCoAgentStateRender` |
| Human approval / edit at interrupt | `useLangGraphInterrupt` |

## Screens (CopilotKit components)

1. **Setup** — ticker + quarter → starts the graph.
2. **Financial Snapshot** — metric cards filled as `facts` stream in.
3. **Market Sentiment** — gauge + theme cards with source citations ([Sentiment](sentiment.md)).
4. **Competitor** — comparison table, leads/lags highlighted ([Competitor](competitor.md)).
5. **Predicted Q&A** — ranked hard questions, each with *why* + evidence chips.
6. **Draft Script (HITL)** — streamed paragraph-by-paragraph; **every sentence shows an evidence
   chip `[F-0012]`**; Approve / Edit / Regenerate resolves the interrupt.
7. **Deck Outline** — bullets per slide (incl. Competitive Position).
8. **Q&A Cheat Sheet** — question → suggested answer → backing facts.

## Streaming mapping

`graph.astream(stream_mode="updates")` ([orchestration](orchestration.md)) → CopilotKit state
deltas → `useCoAgentStateRender` re-renders only the affected component. The HITL interrupt is
surfaced by `useLangGraphInterrupt`; the resolution resumes the graph with the human's decision.

## Optional: Flutter GenUI

A Flutter front-end using `genui` + `genui_a2a` is supported as an alternative for a
mobile/desktop demo. The backend exposes an **A2A WebSocket**; Flutter connects with
`A2uiAgentConnector` and renders **A2UI v0.9** messages.

```dart
final _controller = SurfaceController(catalogs: [
  BasicCatalogItems.asCatalog().copyWith([
    financialSnapshotCard, sentimentGauge, competitorTable,
    predictedQaList, draftSectionWithCitations, evidenceChip, approveEditBar,
  ]),
]);
final _transport  = A2uiTransportAdapter(onSend: _sendToAgent);
final _connector  = A2uiAgentConnector(url: Uri.parse('ws://mi300x-node:8080'));
final _conversation = Conversation(controller: _controller, transport: _transport);

_msgSub  = _connector.stream.listen(_transport.addMessage);    // structured A2UI
_textSub = _connector.textStream.listen(_transport.addChunk);  // streamed text
```

A2UI rules we respect: one `id:"root"` per surface; `createSurface` before
`updateComponents`; `catalogId = https://a2ui.org/specification/v0_9/basic_catalog.json`; every
block has `"version":"v0.9"`; dispose order `conversation → transport → controller → connector`.
Agent updates map to `updateComponents` (new card) / `updateDataModel` (value fill); the HITL
button dispatches a `UserActionEvent` that resumes the LangGraph interrupt.

!!! info "Why CopilotKit is primary"
    CopilotKit pairs natively with Python LangGraph (AG-UI), so streaming, state sync, and
    interrupts work out of the box with the least glue. Flutter GenUI remains available for a
    richer/native demo but is optional for the hackathon.
