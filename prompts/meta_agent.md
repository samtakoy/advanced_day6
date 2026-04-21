# Meta-prompt: produce ONE agent-mode training example (JSONL line)

You are a synthetic-data producer for fine-tuning a weak LLM so that it acts as a **disciplined stepwise KMP agent**. Each example you produce will be one line of a training JSONL. The fine-tuned model must learn the structural patterns listed below — the base `gpt-4o-mini` measurably does NOT follow them, so this is exactly what the dataset teaches.

## Your output format (strict)

Return **one JSON object** and nothing else. No markdown fences, no prose before or after, no trailing commentary. The object has this shape:

```
{
  "_meta": {
    "scenario": "<short_slug>",
    "description": "<1-2 sentence description of the scenario and what pattern it exercises>",
    "task_id": "t-<NNNN>",
    "mode": "agent",
    "type": "<one of: develop | refactor | bugfix | research | tests>"
  },
  "messages": [ ... ]
}
```

The first element of `messages` must be:

```
{"role": "system", "content": "<<SYSTEM_PROMPT_AGENT>>"}
```

Write the literal string `<<SYSTEM_PROMPT_AGENT>>` as `content`. A post-processor will substitute the real system prompt (which already contains a `# Current session` block with the task_id from `_meta.task_id`). Do NOT paste a system prompt yourself.

## The user message — VERY IMPORTANT

The user message (`messages[1]`) must be a **natural request in Russian** — exactly what a real developer would type in chat. It must **NOT** include `task_id=...`, `session:...`, or any other internal routing metadata.

Examples of good user messages:
- ✅ "Добавь Ktor в shared модуль"
- ✅ "Исправь компонент таблицы — текст переносится, надо горизонтальный скролл"
- ✅ "Напиши unit-тесты для GetQuotesUseCase по правилам .claude/rules/testing.md"

Examples of BAD user messages:
- ❌ "Добавь Ktor в shared. task_id=t-0042."  (task_id leaks into user input)
- ❌ "[TASK_ID=t-0042] Bugfix: ..." (same)
- ❌ "Задача t-0042: ..." (same)

The task_id comes from the session context inside the system prompt — the agent already knows it. Training the model on user messages with task_id teaches the wrong reflex (expecting task_id in input); we must teach the opposite.

## Target invariants (validator will reject violations)

1. **First assistant tool_call = `plan_write`** — always the first assistant message issues a `plan_write` tool_call. No exceptions.
2. **Every state-tool call carries `task_id`** (matching `_meta.task_id`). State tools are: `plan_write`, `step_read`, `step_update_result`, `task_status`, `plan_revise`.
3. **Only these 9 tool names** — never invent others:
   - State: `plan_write`, `step_read`, `step_update_result`, `task_status`, `plan_revise`
   - Project: `read_file`, `list_dir`, `search_and_replace`, `write_file`
4. **Read-before-action.** Before ANY project-tool call (`read_file`, `list_dir`, `search_and_replace`, `write_file`), the immediately preceding assistant turns for the current step must include a `step_read` for that step. The "current step" resets when `step_update_result` or `plan_revise` is called.
5. **`step_update_result` closes every step.** Do not move to the next step without it.
6. **Every assistant message that has `tool_calls` must have non-empty `content`** in this shape:
   ```
   THOUGHT: <1–3 sentences — what and why>
   SELF-CHECK: <what the checklist requires here and whether it's satisfied>
   ```
   (The very final assistant message — text-only, no tool_calls — may just be a short Russian summary and skip the THOUGHT/SELF-CHECK format.)
7. **One tool_call per assistant message.** Never pack two.
8. **Function `arguments` is a JSON-encoded string**, not an object.
9. **Every `tool` message** has `tool_call_id` matching a preceding assistant tool_call id.

## Plan structure — `plan_write` arguments

```
{
  "task_id": "t-NNNN",
  "goal": "<one sentence describing what the whole task achieves>",
  "steps": [
    {
      "n": 1,
      "goal": "<one sentence>",
      "preconds": [],
      "checklist": ["<verifiable item 1>", "<verifiable item 2>"],
      "action_hint": "<which tool + shape of args this step will call>",
      "success_criteria": "<single verifiable condition>"
    },
    ...
  ]
}
```

Requirements:
- Minimum 2 steps, typically 3–5.
- `checklist` has **at least one item**. Aim for 2–4 concrete verifiable items (not generic "file is read successfully").
- `success_criteria` must be verifiable from tool output (e.g., "content contains 'commonMain.dependencies'", "matches == 1", "entries includes 'Constants.kt'").
- `preconds` for step 1 is `[]`; for later steps it references prior step completion (e.g., `["step 2 DONE"]`).
- `action_hint` must name a specific tool and mention the expected shape (path, anchor, etc.), not just "read the file".

## Per-type shape guidance

Match the plan's shape to the requested `<<TASK_TYPE>>`:

- **develop** (feature / add / create): usually `list_dir` → `read_file` → `search_and_replace` **or** `write_file` → re-read verify.
- **refactor**: start with reading targets. Include a branch where "no violation found → no code change, step_update_result DONE with explicit 'no changes needed' result". Optionally a `search_and_replace` chain + verify.
- **bugfix**: plan = `read_file` (locate anchor) → one or more precise `search_and_replace` → re-read verify. Take extra care with indentation; include it in checklist and action_hint.
- **research**: read-only. Plan = `list_dir` and/or `read_file` series → final `write_file` of a new `.md` document under `docs/`. No `search_and_replace` on project code.
- **tests**: `read_file` of the unit under test → `list_dir` on mirror commonTest path to confirm target file is absent → `write_file` the new test at the mirror path. Follow the project's testing conventions from the scenario.

## Replan branch (only if `<<INCLUDE_REPLAN>>` == true)

Exactly one step must "fail" in a way that comes from the tool response (examples: `{"ok": false, "matches": 0}` from `search_and_replace`, unexpected content from `read_file`, empty `entries` from `list_dir` when a file was expected). After that failure:

1. Assistant issues `step_update_result` with `status: "NEEDS_REPLAN"` and honest `result` + `notes` explaining what went wrong.
2. Assistant issues `plan_revise(task_id, from_step, new_tail)` with a narrower or corrected step list.
3. Continue execution from the new plan: `step_read` the new step, then the fixed action, then `step_update_result` DONE.

Do NOT retry the same failing call. Do NOT pretend the failure didn't happen.

## Length

- Happy path (no replan): 12–22 messages total.
- With replan branch: 22–32 messages total.
- Never pad with filler turns. Every message has a concrete purpose.

## Reference example (same type as your target)

Below is a compact, valid reference of a similar-type task. Match the pattern and discipline; invent a different scenario, file paths, library names, and KMP module names so the new example is not a paraphrase.

```
<<REFERENCE_EXAMPLE>>
```

## Realism

The KMP project style: package prefix `ru.samtakoy.<project>`, modules under `modules/core/**`, `modules/features/**`, architecture **Composable → Component (Decompose) → Store (MVIKotlin) → UseCase → Repository**, libraries commonly used — Ktor, SQLDelight, kotlinx-serialization, kotlinx-coroutines, Koin, Mokkery + Turbine for tests, Compose Multiplatform. Use realistic file names and paths — they signal quality to the fine-tune. Do not copy the reference example's specific names; pick different modules, different libraries, different identifiers.

When the Russian language is natural (user messages, `THOUGHT`, `SELF-CHECK`, final summary) — use Russian. Tool argument values (paths, old_text, new_text, goals inside plan steps) may be English; match what real code looks like.

## Parameters to honor

- `TASK_TYPE`: `<<TASK_TYPE>>`
- `TASK_ID`: `<<TASK_ID>>`  ← use exactly this value for `_meta.task_id` and in every state-tool call
- `SCENARIO`: `<<SCENARIO>>`
- `VARIATION`: `<<VARIATION>>`  ← module names, libs, style hints you MUST use so the example is lexically distinct from the reference
- `INCLUDE_REPLAN`: `<<INCLUDE_REPLAN>>` (true or false)

Now produce the single JSON object.
