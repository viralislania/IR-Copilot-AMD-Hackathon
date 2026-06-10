# CatalogItem Patterns

Full reference for writing correct CatalogItems in genui.

---

## Anatomy of a CatalogItem

```dart
final myCatalogItem = CatalogItem(
  name: 'MyWidget',             // exact string the LLM uses in "component"
  dataSchema: _schema,           // S.object(...) — do NOT include "component" property
  widgetBuilder: (itemContext) { // receives CatalogItemContext
    // parse data, build Flutter widget
    return MyFlutterWidget(...);
  },
  isImplicitlyFlexible: false,   // set true for widgets needing bounded constraints
  exampleData: [                  // optional; used by CatalogView dev tool
    () => '''[{"id":"root","component":"MyWidget","text":"Hello"}]''',
  ],
);
```

The `component` discriminator property is **automatically injected** into `dataSchema`
by the framework. Never add it manually — it will be silently ignored.

---

## Schema definition

Use `json_schema_builder` (`S.object`, `S.string`, `S.number`, etc.):

```dart
import 'package:json_schema_builder/json_schema_builder.dart';
import 'package:genui/genui.dart'; // for A2uiSchemas

final _schema = S.object(
  description: 'A card showing a riddle.',
  properties: {
    // Static string or data-model binding — use A2uiSchemas.stringReference()
    'question': A2uiSchemas.stringReference(
      description: 'The riddle question.',
    ),
    'answer': A2uiSchemas.stringReference(
      description: 'The hidden answer.',
    ),
    // Reference to another component by ID — use A2uiSchemas.componentReference()
    'child': A2uiSchemas.componentReference(
      description: 'Optional child widget ID.',
    ),
    // Button/submit action — use A2uiSchemas.action()
    'action': A2uiSchemas.action(),
    // Enum
    'variant': S.string(enumValues: ['default', 'compact']),
    // Validation checks
    'checks': A2uiSchemas.checkable(),
  },
  required: ['question', 'answer'],
);
```

`A2uiSchemas.stringReference()` allows both a literal string and a
`{"path": "/some/path"}` binding — always prefer it over bare `S.string()` for
any property that might be reactive.

---

## Extension-type data class (preferred pattern)

The genui built-in widgets use Dart extension types for zero-overhead data parsing:

```dart
extension type _RiddleData.fromMap(JsonMap _json) {
  factory _RiddleData({
    required Object? question,
    required Object? answer,
    JsonMap? action,
    String? variant,
  }) => _RiddleData.fromMap({
    'question': question,
    'answer': answer,
    'action': action,
    'variant': variant,
  });

  // For stringReference fields, keep as Object? so binding resolution works
  Object? get question => _json['question'];
  Object? get answer   => _json['answer'];
  JsonMap? get action  => _json['action'] as JsonMap?;
  String? get variant  => _json['variant'] as String?;
}
```

If you prefer the simpler class-based approach (from the `create-catalog-item` skill):

```dart
class _RiddleData {
  final String question;
  final String answer;
  final JsonMap? action;

  _RiddleData({required this.question, required this.answer, this.action});

  factory _RiddleData.fromJson(Map<String, Object?> json) {
    try {
      return _RiddleData(
        question: json['question'] as String,
        answer:   json['answer']   as String,
        action:   json['action']   as JsonMap?,
      );
    } catch (e) {
      throw Exception('Invalid JSON for _RiddleData: $e');
    }
  }
}
```

Use extension types when fields may be `{"path": "..."}` bindings (reactive).
Use class-based when all fields are guaranteed static values.

---

## Reactive data binding in widgetBuilder

For properties that can be either a static value or a `{"path": "..."}` binding,
use the built-in `BoundString` / `BoundObject` widgets from `widget_utilities`:

```dart
widgetBuilder: (itemContext) {
  final data = _RiddleData.fromMap(itemContext.data as JsonMap);

  return BoundString(
    dataContext: itemContext.dataContext,
    value: data.question,          // passes through either literal or path-map
    builder: (context, question) {
      return BoundString(
        dataContext: itemContext.dataContext,
        value: data.answer,
        builder: (context, answer) {
          return RiddleWidget(question: question ?? '', answer: answer ?? '');
        },
      );
    },
  );
},
```

Alternatively, use `DataContext.subscribe<T>(DataPath(...))` directly for fine-grained
`ValueListenableBuilder` control, which avoids nested builders.

---

## Action handling

When a user taps a button or submits a form, you dispatch a `UserActionEvent`.
The pattern is always: parse the action map → resolve context → dispatch.

```dart
widgetBuilder: (itemContext) {
  final data = _RiddleData.fromMap(itemContext.data as JsonMap);

  return ElevatedButton(
    onPressed: () async {
      final action = data.action;
      if (action == null) return;

      if (action.containsKey('event')) {
        final eventMap = action['event'] as JsonMap;
        final name = eventMap['name'] as String;
        final contextDef = eventMap['context'] as JsonMap?;

        // resolveContext resolves any {"path":"..."} references in the context map
        final resolved = await resolveContext(itemContext.dataContext, contextDef);

        itemContext.dispatchEvent(UserActionEvent(
          name: name,
          sourceComponentId: itemContext.id,
          context: resolved,
        ));
      } else if (action.containsKey('functionCall')) {
        final funcMap = action['functionCall'] as JsonMap;
        if ((funcMap['call'] as String?) == 'closeModal') {
          Navigator.of(itemContext.buildContext).pop();
          return;
        }
        await itemContext.dataContext.resolve(funcMap).first;
      }
    },
    child: Text('Reveal Answer'),
  );
},
```

`resolveContext` is `async` — always `await` it inside an `async` handler.
It resolves `{"path": "..."}` and `{"call": "..."}` values in the context
definition so the event carries real data values, not path references.

---

## Validation / checks

Use `A2uiSchemas.checkable()` in the schema, then gate the button with
`ValidationHelper.validateStream`:

```dart
widgetBuilder: (itemContext) {
  final data = _MyData.fromMap(itemContext.data as JsonMap);
  return StreamBuilder<String?>(
    stream: ValidationHelper.validateStream(data.checks, itemContext.dataContext),
    builder: (context, snapshot) {
      final enabled = snapshot.data == null; // null = all checks passed
      return ElevatedButton(
        onPressed: enabled ? () => _handlePress(itemContext, data) : null,
        child: Text('Submit'),
      );
    },
  );
},
```

---

## Template-based dynamic lists (data-driven children)

For lists where the LLM passes data and a template component ID rather than
explicit child IDs, use `ComponentChildrenBuilder`:

AI sends:
```json
{ "id": "root", "component": "ItemList",
  "children": { "path": "/items", "componentId": "itemTemplate" } }
```

In the widget builder:
```dart
widgetBuilder: (itemContext) {
  final childrenData = (itemContext.data as JsonMap)['children'];
  return ComponentChildrenBuilder(
    childrenData: childrenData,
    dataContext: itemContext.dataContext,
    buildChild: itemContext.buildChild,
    getComponent: itemContext.getComponent,
    explicitListBuilder: (ids, buildChild, _, __) =>
        Column(children: ids.map((id) => buildChild(id)).toList()),
    templateListWidgetBuilder: (context, data, componentId, path) {
      if (data is! List) return const SizedBox.shrink();
      return Column(
        children: List.generate(data.length, (i) {
          final nested = itemContext.dataContext.nested(DataPath('$path/$i'));
          return itemContext.buildChild(componentId, nested);
        }),
      );
    },
  );
},
```

---

## `isImplicitlyFlexible`

Set `isImplicitlyFlexible: true` on any widget that needs **bounded constraints**
when placed inside a `Row` or `Column` (i.e., widgets that call `ListView`,
`TextField`, or otherwise need a maximum size):

```dart
final myListWidget = CatalogItem(
  name: 'MyScrollableList',
  isImplicitlyFlexible: true,   // Row/Column auto-wraps this in Flexible
  dataSchema: _schema,
  widgetBuilder: (itemContext) => ListView(...),
);
```

Without this flag, the widget will throw an unbounded-constraints error inside flex
layouts.

---

## exampleData

`exampleData` feeds the `CatalogView` development tool and helps you capture real
model output. Each entry is a lambda returning a JSON string of the full
`components` list (including `root`):

```dart
exampleData: [
  () => '''
    [
      { "id": "root", "component": "RiddleCard",
        "question": "I speak without a mouth. What am I?",
        "answer": "An echo" }
    ]
  ''',
],
```

To capture real model output: enable `Level.ALL` logging and search the console for
`"definition": {` — that's the raw JSON genui received.

---

## Adding the item to a SurfaceController

```dart
_controller = SurfaceController(
  catalogs: [
    BasicCatalogItems.asCatalog().copyWith([riddleCard, kycWidget]),
  ],
);
```

Then update the system prompt (via `PromptBuilder`) to include instructions and
examples for your new widgets — the catalog's schema is automatically included, but
the model benefits from a sentence or two explaining when to use each custom widget.
