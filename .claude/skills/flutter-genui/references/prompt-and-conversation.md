# PromptBuilder & Conversation Patterns

---

## PromptBuilder modes

### Chat mode (most common)
Each LLM turn creates a **new** surface. The model is told not to update or delete
existing surfaces. Good for conversational UIs where each response is a fresh card.

```dart
final promptBuilder = PromptBuilder.chat(
  catalog: catalog,
  systemPromptFragments: [
    'You are a KYC compliance assistant. Be concise.',
    PromptFragments.acknowledgeUser(),
    PromptFragments.requireAtLeastOneSubmitElement(),
    PromptFragments.currentDate(),
  ],
);
// Send as the first message before any user input:
_conversation.sendRequest(ChatMessage.system(promptBuilder.systemPromptJoined()));
```

`systemPromptJoined()` merges all fragments with a separator — use it when your LLM
expects a single string system message. Use `systemPrompt()` (returns `Iterable<String>`)
when the LLM accepts multi-part system prompts.

### Custom mode — persistent / updatable UI
Use when the model should update the same surface across multiple turns (e.g., a
dashboard that evolves as the user chats):

```dart
final promptBuilder = PromptBuilder.custom(
  catalog: catalog,
  allowedOperations: SurfaceOperations.createAndUpdate(dataModel: true),
  // Or SurfaceOperations.all(dataModel: true) to also allow deleteSurface
  systemPromptFragments: ['You manage a live KYC risk dashboard.'],
);
```

Available `SurfaceOperations` factory constructors:

| Constructor | Creates | Updates | Deletes | DataModel |
|---|---|---|---|---|
| `createOnly(dataModel: …)` | ✓ | ✗ | ✗ | configurable |
| `updateOnly(dataModel: …)` | ✗ | ✓ | ✗ | configurable |
| `createAndUpdate(dataModel: …)` | ✓ | ✓ | ✗ | configurable |
| `all(dataModel: …)` | ✓ | ✓ | ✓ | configurable |

Set `dataModel: true` whenever the model needs to use `updateDataModel` (reactive
field updates, form state, etc.).

---

## PromptFragments

These are composable system-prompt snippets:

```dart
PromptFragments.acknowledgeUser()
// → "Your responses should contain acknowledgment of the user message."

PromptFragments.requireAtLeastOneSubmitElement()
// → "When asking for info, always include at least one submit button..."

PromptFragments.currentDate()
// → "Current Date: 2026-06-04"

PromptFragments.uiGenerationRestriction()
// → "Do not use tools or function calls for UI generation. Use JSON text blocks..."
```

All fragments accept an optional `prefix:` parameter (defaults to `''`). Pass
`PromptBuilder.defaultImportancePrefix` (`"IMPORTANT: "`) to emphasise critical rules.

---

## Sending messages

```dart
// Initial system prompt (before user interaction)
_conversation.sendRequest(ChatMessage.system(systemPrompt));

// User text turn
_conversation.sendRequest(ChatMessage.user('I need to verify John Smith'));

// System turn mid-conversation (e.g. inject context)
_conversation.sendRequest(ChatMessage.system('Additional context: ...'));
```

`ChatMessage` parts may include `TextPart` (text) and `UiInteractionPart`
(user action events / validation errors from the framework). When you forward
the message to your LLM, concatenate all parts — including `UiInteractionPart`
so the model sees what the user did.

---

## ConversationState notifier

`_conversation.state` is a `ValueListenable<ConversationState>`. Use it for simple
reactive state without a full event stream listener:

```dart
ValueListenableBuilder<ConversationState>(
  valueListenable: _conversation.state,
  builder: (context, state, _) {
    return Column(children: [
      if (state.isWaiting) const LinearProgressIndicator(),
      ...state.surfaces.map((id) =>
          Surface(host: _conversation.host, surfaceId: id)),
    ]);
  },
);
```

`state.surfaces` is the ordered list of active surface IDs.
`state.latestText` is the most recent raw text chunk (for displaying streamed text).
`state.isWaiting` is true while the LLM is generating.

---

## Multi-turn history

`Conversation` / `A2uiTransportAdapter` do **not** manage conversation history
internally — that is the responsibility of your LLM client. Typical patterns:

**Firebase AI / Vertex AI:** Use `model.startChat()` which manages history
automatically. Just call `_chatSession.sendMessage(Content.text(text))` per turn.

**OpenAI-compatible (vLLM, llama.cpp):** Maintain a `List<Map>` messages array
yourself. Each call to `onSend`, append the new user message and send the full history.

**Important:** The framework sends UI interaction events (button presses, errors) back
through `Conversation.sendRequest` automatically. These arrive as messages whose
`parts` include a `UiInteractionPart`. Make sure your LLM integration serialises
those parts — they tell the model what the user did in the UI so it can react.

---

## Error handling

`SurfaceController` catches A2UI validation errors and sends them back to the LLM
automatically as a `ChatMessage` with an error JSON payload:

```json
{ "version": "v0.9", "error": { "code": "VALIDATION_FAILED", "surfaceId": "main",
  "path": "components/0/action", "message": "..." } }
```

Listen to `ConversationError` events for network/LLM errors:

```dart
case ConversationError(:final error, :final stackTrace):
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text('Error: $error')),
  );
```

---

## Disposal checklist

In the `State.dispose()` method, always dispose in this order:

```dart
@override
void dispose() {
  _conversation.dispose();  // closes event stream, cancels subscriptions
  _transport.dispose();     // closes incoming message stream
  _controller.dispose();    // closes surface registry, data model store
  super.dispose();
}
```

Failing to dispose `SurfaceController` leaks `Timer` objects (the pending-update
buffers that wait up to 1 minute for a `createSurface` before discarding buffered
`updateComponents` messages).

---

## Development utility: CatalogView

`CatalogView` lets you browse and render your widget catalog without an LLM, using
the `exampleData` entries on each `CatalogItem`. Wrap it in a debug screen:

```dart
if (kDebugMode)
  ElevatedButton(
    onPressed: () => Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => CatalogView(catalog: catalog)),
    ),
    child: Text('Dev: Catalog View'),
  ),
```

This is invaluable for testing widget layouts before wiring up the real LLM.

---

## iOS / macOS network entitlements

If you build for iOS or macOS and hit network errors when calling your LLM, add
the outbound network key to both `*.entitlements` files:

```xml
<key>com.apple.security.network.client</key>
<true/>
```

File locations: `ios/Runner/DebugProfile.entitlements`, `ios/Runner/Release.entitlements`,
and the equivalent `macos/Runner/` files.
