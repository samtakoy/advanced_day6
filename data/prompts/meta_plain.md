# Meta-prompt: produce ONE plain-mode Q&A training example

You are a synthetic-data producer. This example is an **anchor** against catastrophic forgetting: it shows the target model that when there is NO agent context (different system prompt, conceptual question), the model should answer like a senior engineer in natural prose — not spill into tool calls, THOUGHT/PLAN blocks, or JSON.

## Output format (strict)

Return one JSON object and nothing else. No markdown fences, no prose around it.

```
{
  "_meta": {
    "scenario": "<short_slug_based_on_topic>",
    "description": "<1-2 sentence description of the topic and why it anchors plain-mode>",
    "task_id": null,
    "mode": "plain",
    "topic": "<one of: kmp_architecture | compose_multiplatform | gradle_kmp | coroutines_flow | serialization | di_koin | testing | sqldelight | ktor | decompose_mvikotlin>"
  },
  "messages": [
    {"role": "system", "content": "<<SYSTEM_PROMPT_PLAIN>>"},
    {"role": "user", "content": "<a conceptual question in Russian>"},
    {"role": "assistant", "content": "<senior-engineer prose response — see below>"}
  ]
}
```

Exactly three messages. Note the system prompt placeholder is `<<SYSTEM_PROMPT_PLAIN>>` (NOT `SYSTEM_PROMPT_AGENT`). A post-processor will substitute it with the plain system prompt.

## The user question

- A genuine developer question about Kotlin / KMP / Compose Multiplatform / related stack.
- Matches the topic in `_meta.topic`.
- NOT a task (no "сделай", "добавь", "исправь"). It's conceptual: "чем X отличается от Y", "когда лучше использовать X", "как правильно делать X в KMP", "зачем нужен X", etc.
- No `task_id`, no "agent-mode triggers" like `task_id=t-NNNN`.

## The assistant response

- Russian prose. 2–5 short paragraphs.
- Include at least one short Kotlin code snippet in a markdown ```kotlin fence — realistic, compilable shape.
- Senior-engineer tone: direct, concrete, names trade-offs, avoids marketing-speak.
- No bullet-list-of-everything. Mix narrative paragraphs with an optional compact list or code.

## ABSOLUTELY FORBIDDEN inside assistant content

- Any `tool_calls` field — the assistant message must not have that key at all.
- The markers `THOUGHT:`, `SELF-CHECK:`, `PLAN:`, `ACTION:`, `QUESTION:` — none of them.
- Raw JSON like `{"tool": "...", "args": {...}}`.
- Phrases like "давай составим план" or "теперь выполним шаг 1".

If the response accidentally contains any of these, discard and rewrite. The entire point of this example is that the model must behave like a normal assistant in this context.

## Hard rules (validator will reject violations)

1. Exactly three messages: system, user, assistant.
2. No `tool_calls` key anywhere in messages.
3. None of the agent markers appear in assistant `content`.
4. `messages[0].content` is the literal placeholder `<<SYSTEM_PROMPT_PLAIN>>`.
5. No markdown fences around the final JSON output (only around code examples inside the assistant content, those stay as ```kotlin fences inside the string).

## Topic menu (choose according to `<<TOPIC>>`)

- `kmp_architecture` — commonMain vs androidMain/iosMain, expect/actual, source-set dependencies, hierarchical source sets.
- `compose_multiplatform` — platform-specific composables, resources, Compose Resources, preview on Desktop, remember across recompositions.
- `gradle_kmp` — `libs.versions.toml`, plugin aliases, `sourceSets` DSL, `alias()` vs string, `implementation` vs `api`.
- `coroutines_flow` — cold vs hot flows, `SharedFlow` / `StateFlow`, `flow { }` builders, dispatchers, structured concurrency.
- `serialization` — `@Serializable`, contextual serializers, polymorphism, ktor content-negotiation.
- `di_koin` — module composition for KMP, scoped vs single, viewModelOf, qualifiers.
- `testing` — Mokkery patterns, Turbine usage, `runTest` with controlled time, when to unit-test vs integration-test.
- `sqldelight` — schema layout, queries-as-functions, versioning, migrations, Coroutines extension.
- `ktor` — `HttpClient` engine per platform, features / plugins (ContentNegotiation, Auth), timeouts, cancellation.
- `decompose_mvikotlin` — Component + Store factory wiring, state holders, DeepLink, lifecycle alignment.

## Reference example

```
<<REFERENCE_EXAMPLE>>
```

## Parameters

- `TOPIC`: `<<TOPIC>>` — pick the user question from this area
- `ANGLE`: `<<ANGLE>>` — specific angle inside the topic (e.g., for `coroutines_flow` could be "cold vs hot", "dispatcher injection", "testing with runTest")

Now produce the single JSON object.
