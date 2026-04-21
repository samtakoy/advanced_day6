# Meta-prompt: produce ONE agent_question training example

You are a synthetic-data producer. This example teaches the model to **refuse to act** when the user request is underspecified — and instead ask a precise clarifying question. The base `gpt-4o-mini` measurably fails at this: it writes a speculative plan instead of asking. Our target model must learn the opposite reflex.

## Output format (strict)

Return one JSON object and nothing else. No markdown fences, no prose around it.

```
{
  "_meta": {
    "scenario": "<short_slug>",
    "description": "<1-2 sentence description of the ambiguity this example covers>",
    "task_id": "t-<NNNN>",
    "mode": "agent_question",
    "ambiguity_axis": "<one of: library_choice | target_module | scope_breadth | format | behavior | priority>"
  },
  "messages": [
    {"role": "system", "content": "<<SYSTEM_PROMPT_AGENT>>"},
    {"role": "user", "content": "<underspecified task + task_id=t-NNNN>"},
    {"role": "assistant", "content": "<single text response — see below>"}
  ]
}
```

Exactly **three** messages. The assistant message has NO `tool_calls`.

## What the assistant content must contain

The assistant content is a single Russian text with three structural blocks on separate lines, in this order:

```
THOUGHT: <1-3 sentences — what is ambiguous, why a speculative plan would be wrong>
SELF-CHECK: <explicit reasoning: "для plan_write требуется X, Y, Z — не определено ничего из X, нет Y, Z неясно">
QUESTION: <concrete numbered clarifying questions — 2-4 items>
```

Each `QUESTION:` item must be narrow enough that a human can answer in one short sentence. Do **not** produce open-ended consultation questions like "чего вы хотите?". Aim for forced-choice framings where possible ("SQLDelight, Room через KMP-обёртку, Realm или другое?").

## The user message (what drives diversity)

The user message must be an **underspecified KMP task**. It should sound like a real developer's one-liner in a chat. Pick an ambiguity axis (from `_meta.ambiguity_axis`):

- **library_choice**: user says "добавь базу данных" or "логгирование" without naming engine.
- **target_module**: user says "поправь экран" in project with multiple feature modules.
- **scope_breadth**: user asks for a sweeping refactor ("перенеси всё на Voyager") without scope constraints.
- **format**: user asks for output that could be produced in several incompatible formats.
- **behavior**: user says "сделай чтобы на iOS работало по-другому" without specifying what.
- **priority**: user gives conflicting criteria (e.g., "сохрани совместимость API И измени поведение этого метода").

The user message MUST be natural — NO `task_id=`, NO session metadata, NO prefixes. The task_id lives in the session part of the system prompt; real users don't include it. Good example: "Добавь в проект локальную базу данных."  Bad example: "Добавь в проект локальную базу данных. task_id=t-0077."

## Hard rules (validator will reject violations)

1. Exactly three messages: system, user, assistant.
2. Assistant has `content` but NO `tool_calls`.
3. Content contains the substring `QUESTION:` in the final block.
4. No JSON tool-call-style text in the content (no `{"tool": ...}`).
5. `messages[0].content` is the literal placeholder `<<SYSTEM_PROMPT_AGENT>>`.
6. No markdown fences around the final JSON output.

## Style

- All three blocks (THOUGHT / SELF-CHECK / QUESTION) in Russian.
- No fake confidence. The assistant should explicitly say: "план без ответа на X.Y.Z. будет угадыванием".
- KMP-specific realism in user message (mention real-sounding modules like `feature-auth`, `core-features/stocks`, files like `build.gradle.kts`, `libs.versions.toml`, `expect/actual`).

## Reference example

```
<<REFERENCE_EXAMPLE>>
```

## Parameters

- `TASK_ID`: `<<TASK_ID>>`
- `AMBIGUITY_AXIS`: `<<AMBIGUITY_AXIS>>`
- `VARIATION`: `<<VARIATION>>` — topical hint for the user request (e.g., "network layer", "compose navigation", "error handling")

Now produce the single JSON object.
