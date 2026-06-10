---
name: flutter-genui
description: >
  Expert guide for developing Flutter apps with the `genui` package — covering
  the A2UI v0.9 protocol, widget catalog creation, DataModel binding, Conversation
  wiring, PromptBuilder, Surface rendering, and the genui_a2a A2A WebSocket transport.
  Trigger this skill whenever the user is building, debugging, or extending a Flutter
  app that uses `genui` or `genui_a2a`, mentions `CatalogItem`, `SurfaceController`,
  `Conversation`, `A2uiTransportAdapter`, `A2uiAgentConnector`, `Surface` widget,
  `PromptBuilder`, `updateComponents`, `createSurface`, `deleteSurface`, or asks how
  generative UI works in Flutter. Also trigger when the user asks how to add a custom
  widget to the catalog, how to handle button actions, how to bind data reactively,
  how to wire up an LLM (Firebase AI, Vertex AI, llama.cpp, OpenAI-compat) to a
  Flutter UI, or how to connect to an A2A WebSocket server.
---

# Flutter genui Development Guide

`genui` is Flutter's package for generative UI (A2UI protocol v0.9): an LLM outputs
structured JSON messages embedded in its text stream; the framework parses them and
renders live Flutter widgets. Two transport paths exist — choose the right one:

| Scenario | Transport |
|---|---|
| LLM outputs streaming text with embedded ```json blocks | `A2uiTransportAdapter` + `addChunk()` |
| Backend is an A2A WebSocket server | `genui_a2a` package → `A2uiAgentConnector` |
| Direct tool/function-call API (OpenAI style) | `catalogToFunctionDeclaration` + `addMessage()` |

---

## Architecture layers (from source)

```
Transport Layer       A2uiTransportAdapter  ←→  A2uiParserTransformer
                      A2uiAgentConnector (genui_a2a, WebSocket)
        ↕
Engine Layer          SurfaceController  →  DataModel  →  SurfaceRegistry
        ↕
Widget Layer          Surface  →  CatalogItem.widgetBuilder  →  Flutter widgets
        ↕
Facade Layer          Conversation  (orchestrates all of the above)
```

---

## Standard wiring (streaming text / llama.cpp / OpenAI-compat)

```dart
// Three objects, always instantiated together
final _controller   = SurfaceController(catalogs: [BasicCatalogItems.asCatalog()]);
final _transport    = A2uiTransportAdapter(onSend: _sendAndReceive);
final _conversation = Conversation(controller: _controller, transport: _transport);

// Dispose order matters — reverse of construction
@override
void dispose() {
  _conversation.dispose();   // cancels subscriptions
  _transport.dispose();      // closes incoming streams
  _controller.dispose();     // cancels pending timers, closes surface registry
  super.dispose();
}
```

---

## A2A WebSocket wiring (`genui_a2a`)

Use when your backend is a server implementing the A2A protocol (WebSocket, not SSE).

```dart
// pubspec.yaml: flutter pub add genui genui_a2a
final _controller  = SurfaceController(catalogs: [BasicCatalogItems.asCatalog()]);
final _transport   = A2uiTransportAdapter(onSend: _sendToAgent);
final _connector   = A2uiAgentConnector(url: Uri.parse('ws://localhost:8080'));
final _conversation = Conversation(controller: _controller, transport: _transport);

// Pipe connector output → transport (two streams)
_msgSub  = _connector.stream.listen(_transport.addMessage);   // structured A2uiMessages
_textSub = _connector.textStream.listen(_transport.addChunk); // raw text chunks

Future<void> _sendToAgent(ChatMessage msg) async {
  await _connector.connectAndSend(msg);
}

@override
void dispose() {
  _msgSub.cancel();
  _textSub.cancel();
  _conversation.dispose();
  _transport.dispose();
  _controller.dispose();
  _connector.dispose();
  super.dispose();
}
```

`A2uiAgentConnector` maintains `taskId` and `contextId` for stateful A2A conversations.
It also exposes `AgentCard` metadata about the connected agent.

---

## A2UI protocol v0.9 — four messages, exact rules

All JSON must be fenced in ` ```json ``` ` blocks. The LLM must NOT use tool/function
calls for UI — `PromptBuilder` instructs the model of this explicitly.

### `createSurface` — surface setup only, no content
```json
{
  "version": "v0.9",
  "createSurface": {
    "surfaceId": "main",
    "catalogId": "https://a2ui.org/specification/v0_9/basic_catalog.json",
    "sendDataModel": true
  }
}
```
- `sendDataModel: true` activates `updateDataModel` for this surface.
- `SurfaceController` buffers `updateComponents` for up to 1 minute waiting for the
  matching `createSurface` — arrival order is tolerated, but both must arrive.
- Never put component data inside `createSurface`.

### `updateComponents` — build or patch the component tree
```json
{
  "version": "v0.9",
  "updateComponents": {
    "surfaceId": "main",
    "components": [
      { "id": "root",  "component": "Column", "children": ["title", "btn"] },
      { "id": "title", "component": "Text",   "text": "Hello" },
      { "id": "btn",   "component": "Button", "child": "label",
        "action": { "event": { "name": "greet_pressed" } } },
      { "id": "label", "component": "Text",   "text": "Say Hi" }
    ]
  }
}
```
**Exactly one component must have `id: "root"`** — this is the render entry point.
Sending components without a `root` renders nothing silently.

`updateComponents` is **additive/patch**: components not mentioned in the payload
are preserved. Send only changed components to minimise re-renders.

### `updateDataModel` — reactive field updates (no re-render)
```json
{ "version": "v0.9", "updateDataModel": { "surfaceId": "main", "path": "/score", "value": 0.87 } }
```
Path format: `/absolute/slash/separated`. Update propagates to all widgets subscribed
to that path or any ancestor path — only those widgets rebuild.

### `deleteSurface` — remove a surface entirely
```json
{ "version": "v0.9", "deleteSurface": { "surfaceId": "old-turn-3" } }
```
Only available when `SurfaceOperations.all(...)` or `SurfaceOperations.delete` is set.

---

## Catalog — what the LLM can render

`BasicCatalogItems.asCatalog()` — all 18 widgets including AudioPlayer, Image, Video.
`BasicCatalogItems.asNoAssetCatalog()` — drops those three for text-only apps.

The `catalogId` string burned into `BasicCatalogItems` is:
`https://a2ui.org/specification/v0_9/basic_catalog.json`
The `createSurface` message must use this exact string for the catalog to be found.

Add custom widgets alongside built-ins:
```dart
SurfaceController(catalogs: [
  BasicCatalogItems.asCatalog().copyWith([riskScoreWidget, evidenceCitationList]),
])
```

> See `references/catalog-item-patterns.md` for the full CatalogItem authoring guide —
> schemas, extension-type data classes, action wiring, reactive binding, validation.

---

## Surface widget

```dart
// Preferred — via SurfaceContext (scoped access to DataModel + catalog):
Surface(surfaceContext: _controller.contextFor(surfaceId))

// Via host reference (Conversation manages surfaces internally):
Surface(host: _conversation.host, surfaceId: surfaceId)

// With loading placeholder:
Surface(
  surfaceContext: _controller.contextFor(surfaceId),
  defaultBuilder: (_) => const CircularProgressIndicator(),
)
```

Track surface IDs from `_conversation.events`:
```dart
_conversation.events.listen((event) {
  switch (event) {
    case ConversationSurfaceAdded(:final surfaceId):
      setState(() => _surfaceIds.add(surfaceId));
    case ConversationSurfaceRemoved(:final surfaceId):
      setState(() => _surfaceIds.remove(surfaceId));
    case ConversationContentReceived(:final text):
      // Raw text (non-JSON parts of the model response)
    case ConversationWaiting():
      setState(() => _isWaiting = true);
    case ConversationError(:final error):
      // Show snackbar / retry
    default: break;
  }
});
```

Or use `_conversation.state` (`ValueListenable<ConversationState>`) for
`state.surfaces`, `state.isWaiting`, `state.latestText` without a stream listener.

---

## PromptBuilder — system prompt generation

`PromptBuilder` embeds the full A2UI JSON schema + catalog description so the model
knows your exact widget vocabulary and which protocol messages it may send.

```dart
// Chat mode — createOnly, no update/delete. New surface per turn.
final pb = PromptBuilder.chat(catalog: catalog, systemPromptFragments: [
  'You are a KYC compliance assistant.',
  PromptFragments.acknowledgeUser(),
  PromptFragments.requireAtLeastOneSubmitElement(),
  PromptFragments.currentDate(),
]);
_conversation.sendRequest(ChatMessage.system(pb.systemPromptJoined()));
```

```dart
// Persistent/dashboard mode — model updates the same surface across turns.
final pb = PromptBuilder.custom(
  catalog: catalog,
  allowedOperations: SurfaceOperations.all(dataModel: true),
  systemPromptFragments: ['You manage a live risk dashboard.'],
);
```

`SurfaceOperations` modes:

| Factory | create | update | delete | dataModel |
|---|---|---|---|---|
| `createOnly(dataModel:)` | ✓ | ✗ | ✗ | config |
| `updateOnly(dataModel:)` | ✗ | ✓ | ✗ | config |
| `createAndUpdate(dataModel:)` | ✓ | ✓ | ✗ | config |
| `all(dataModel:)` | ✓ | ✓ | ✓ | config |

Set `dataModel: true` whenever `updateDataModel` messages are needed.

---

## Wiring your LLM

```dart
Future<void> _sendAndReceive(ChatMessage msg) async {
  final buffer = StringBuffer();
  for (final part in msg.parts) {
    if (part.isUiInteractionPart) {
      // User action events (button taps, form submissions) sent back to LLM
      buffer.write(part.asUiInteractionPart!.interaction);
    } else if (part is genui.TextPart) {  // alias required — see below
      buffer.write(part.text);
    }
  }
  if (buffer.isEmpty) return;

  // For streaming (llama.cpp, OpenAI-compat, vLLM):
  final stream = myLlm.streamChat(buffer.toString());
  await for (final chunk in stream) {
    _transport.addChunk(chunk);   // feed raw text; parser extracts JSON blocks
  }
}
```

**Import conflict (Firebase AI / Vertex AI):**
```dart
import 'package:genui/genui.dart' hide TextPart;
import 'package:genui/genui.dart' as genui;
```

**Direct tool/function-call APIs (OpenAI function calling style):**
```dart
// Convert catalog to OpenAI-style function declaration
final fn = catalogToFunctionDeclaration(catalog);
// When LLM returns a tool call result, feed it directly as a structured message:
_controller.handleMessage(A2uiMessage.fromJson(toolCallResult));
// or via transport:
_transport.addMessage(A2uiMessage.fromJson(toolCallResult));
```

---

## DataModel — reactive binding

Static value or path-binding in component JSON:
```json
{ "id": "score", "component": "Text", "text": { "path": "/risk/score" } }
```

`updateDataModel` or a TextField writing to `/risk/score` triggers only `score`
to rebuild — not the whole surface tree.

Bind external Flutter state to the DataModel:
```dart
final disposeBinding = dataModel.bindExternalState<double>(
  path: DataPath('/risk/score'),
  source: myValueNotifier,
  twoWay: true,   // DataModel changes also update myValueNotifier
);
// Call disposeBinding() in widget dispose()
```

---

## Client-side functions (`FunctionRegistry`)

Register Dart functions the model can call in expressions (validation, formatting):
```dart
final registry = FunctionRegistry()..registerBasicFunctions();
// BasicFunctions include: required, regex, length, and, or, not, formatDate, etc.
registry.register('formatScore', ClientFunction(
  name: 'formatScore',
  execute: (args, _) => Stream.value('${(args['value'] as double * 100).toStringAsFixed(1)}%'),
));
```
Pass the registry via `DataContext` when building catalog items that use `call` expressions.

---

## Development tools

```dart
// DebugCatalogView — browse all catalog items using their exampleData
// (no LLM needed; great for layout testing)
if (kDebugMode)
  Navigator.push(context, MaterialPageRoute(
    builder: (_) => DebugCatalogView(catalog: catalog),
  ));

// FallbackWidget — show in Surface defaultBuilder while loading
Surface(
  surfaceContext: _controller.contextFor(id),
  defaultBuilder: (_) => FallbackWidget(isLoading: true),
)
```

---

## Logging

```dart
// main() — enable before runApp
configureLogging(level: Level.ALL);
Logger.root.onRecord.listen((r) {
  debugPrint('${r.loggerName}: ${r.message}');
  if (r.error != null) debugPrint('Error: ${r.error}');
});
```
Search logs for `"definition": {` to capture real model JSON output → paste into
`exampleData` on your `CatalogItem` for `DebugCatalogView` testing.

---

## Common pitfalls

| Mistake | Fix |
|---|---|
| Nothing renders | One component must have `id: "root"` |
| Surface never appears | `createSurface` must arrive before or within 1 min of `updateComponents` |
| Wrong `catalogId` | Must be `https://a2ui.org/specification/v0_9/basic_catalog.json` for BasicCatalogItems |
| Button does nothing | `resolveContext` + `dispatchEvent(UserActionEvent(...))` missing in widgetBuilder |
| TextField unbounded in Row | Set `isImplicitlyFlexible: true` on the CatalogItem |
| Memory leak | Dispose: `_conversation → _transport → _controller` (+ `_connector` if using genui_a2a) |
| LLM uses tool calls for UI | Add `PromptFragments.uiGenerationRestriction()` to system prompt |
| TextPart import error | `import 'package:genui/genui.dart' hide TextPart;` + alias |
| `version` field missing | Every A2UI JSON block must include `"version": "v0.9"` |
| iOS/macOS network error | Add `com.apple.security.network.client = true` to both `*.entitlements` files |

---

## Reference files

- `references/catalog-item-patterns.md` — CatalogItem schemas, extension-type data
  classes, action wiring, reactive binding, validation checks, template lists,
  `exampleData`, `isImplicitlyFlexible`.
- `references/prompt-and-conversation.md` — PromptBuilder modes, SurfaceOperations,
  ConversationState notifier, multi-turn history, error handling, disposal checklist,
  DebugCatalogView, iOS/macOS entitlements.
