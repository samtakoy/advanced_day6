#!/usr/bin/env python3
"""Validator for fine-tune dataset examples.

Usage:
    python -m src.validator.validate <path>
    python -m src.validator.validate data/seeds/
    python -m src.validator.validate data/out/train.jsonl
    python -m src.validator.validate data/seeds/golden_01.json

Exit code 0 if no errors, 1 if errors found.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import jsonschema


# --- Constants ---

VALID_ROLES = {"system", "user", "assistant", "tool"}

STATE_TOOLS = {"plan_write", "step_read", "step_update_result", "task_status", "plan_revise"}
PROJECT_TOOLS = {"read_file", "list_dir", "search_and_replace", "write_file"}
ALLOWED_TOOL_NAMES = STATE_TOOLS | PROJECT_TOOLS

AGENT_MARKERS = ["THOUGHT:", "SELF-CHECK:", "PLAN:", "ACTION:", "QUESTION:"]


# --- Data types ---

@dataclass
class Issue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    path: str = ""  # e.g., "messages[5].tool_calls[0]"


# --- Loaders ---

def load_examples(path: Path) -> list[tuple[str, dict]]:
    """Load examples from a file or directory.

    Returns list of (source_id, example_dict). For bad JSON, example_dict
    is {"_error": "..."} so structural check can report it.
    """
    if path.is_dir():
        out: list[tuple[str, dict]] = []
        for p in sorted(path.glob("*.json")):
            try:
                with p.open(encoding="utf-8") as f:
                    out.append((p.name, json.load(f)))
            except json.JSONDecodeError as e:
                out.append((p.name, {"_error": f"JSONDecodeError: {e}"}))
        return out
    if path.suffix == ".jsonl":
        out = []
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append((f"line {i}", json.loads(line)))
                except json.JSONDecodeError as e:
                    out.append((f"line {i}", {"_error": f"JSONDecodeError: {e}"}))
        return out
    if path.suffix == ".json":
        try:
            with path.open(encoding="utf-8") as f:
                return [(path.name, json.load(f))]
        except json.JSONDecodeError as e:
            return [(path.name, {"_error": f"JSONDecodeError: {e}"})]
    raise ValueError(f"unknown path type: {path}")


def load_tool_schemas(contracts_dir: Path) -> dict[str, dict]:
    """Return {tool_name: parameters_schema} from tool_schemas.json."""
    with (contracts_dir / "tool_schemas.json").open(encoding="utf-8") as f:
        data = json.load(f)
    return {t["function"]["name"]: t["function"]["parameters"] for t in data["tools"]}


# --- Mode detection ---

def detect_mode(example: dict) -> str:
    """Determine mode: agent / agent_question / plain."""
    meta = example.get("_meta", {}) or {}
    if "mode" in meta:
        return meta["mode"]
    messages = example.get("messages", [])
    has_tool_calls = any(
        m.get("tool_calls")
        for m in messages
        if isinstance(m, dict) and m.get("role") == "assistant"
    )
    if has_tool_calls:
        return "agent"
    has_question = any(
        "QUESTION:" in (m.get("content") or "")
        for m in messages
        if isinstance(m, dict) and m.get("role") == "assistant"
    )
    if has_question:
        return "agent_question"
    return "plain"


# --- Structural checks ---

def check_structural(example: dict) -> list[Issue]:
    issues: list[Issue] = []

    if "_error" in example:
        issues.append(Issue("error", "JSON_PARSE", example["_error"]))
        return issues

    if "messages" not in example:
        issues.append(Issue("error", "NO_MESSAGES", "top-level 'messages' key missing"))
        return issues

    messages = example["messages"]
    if not isinstance(messages, list) or len(messages) < 2:
        issues.append(Issue("error", "MESSAGES_TOO_FEW",
                            f"need >= 2 messages, got {len(messages) if isinstance(messages, list) else 'non-list'}"))
        return issues

    for i, m in enumerate(messages):
        path = f"messages[{i}]"

        if not isinstance(m, dict):
            issues.append(Issue("error", "MESSAGE_NOT_DICT", "message is not an object", path))
            continue

        role = m.get("role")
        if role not in VALID_ROLES:
            issues.append(Issue("error", "BAD_ROLE",
                                f"role='{role}' not in {sorted(VALID_ROLES)}", path))
            continue

        content = m.get("content")
        tool_calls = m.get("tool_calls")

        if role == "system":
            if not isinstance(content, str) or len(content.strip()) < 10:
                issues.append(Issue("error", "SYSTEM_CONTENT_TOO_SHORT",
                                    "system content missing or too short", path))
        elif role == "user":
            if not isinstance(content, str) or len(content.strip()) < 2:
                issues.append(Issue("error", "USER_CONTENT_TOO_SHORT",
                                    "user content missing or too short", path))
        elif role == "assistant":
            if content is None and not tool_calls:
                issues.append(Issue("error", "ASSISTANT_EMPTY",
                                    "assistant has neither content nor tool_calls", path))
            if tool_calls is not None:
                if not isinstance(tool_calls, list) or not tool_calls:
                    issues.append(Issue("error", "TOOL_CALLS_BAD",
                                        "tool_calls must be non-empty array", path))
                else:
                    for j, tc in enumerate(tool_calls):
                        tc_path = f"{path}.tool_calls[{j}]"
                        if not isinstance(tc, dict):
                            issues.append(Issue("error", "TOOL_CALL_NOT_DICT", "tool_call not an object", tc_path))
                            continue
                        if tc.get("type") != "function":
                            issues.append(Issue("error", "BAD_TOOL_CALL_TYPE",
                                                f"type='{tc.get('type')}' (expected 'function')", tc_path))
                        if not tc.get("id"):
                            issues.append(Issue("error", "NO_TOOL_CALL_ID", "missing tool_call id", tc_path))
                        fn = tc.get("function", {}) or {}
                        name = fn.get("name")
                        if name not in ALLOWED_TOOL_NAMES:
                            issues.append(Issue("error", "UNKNOWN_TOOL",
                                                f"tool '{name}' not in allowed set", tc_path))
                        args_str = fn.get("arguments")
                        if not isinstance(args_str, str):
                            issues.append(Issue("error", "ARGS_NOT_STRING",
                                                "function.arguments must be JSON-encoded string", tc_path))
                        else:
                            try:
                                json.loads(args_str)
                            except json.JSONDecodeError as e:
                                issues.append(Issue("error", "ARGS_BAD_JSON",
                                                    f"arguments invalid JSON: {e}", tc_path))
        elif role == "tool":
            if not m.get("tool_call_id"):
                issues.append(Issue("error", "TOOL_NO_CALL_ID", "tool message missing tool_call_id", path))
            if not isinstance(content, str):
                issues.append(Issue("error", "TOOL_CONTENT_MISSING", "tool content missing", path))

        # length upper bound sanity
        if isinstance(content, str) and len(content) > 12000:
            issues.append(Issue("warning", "CONTENT_TOO_LONG",
                                f"content length {len(content)} > 12000 chars", path))

    # ordering sanity: first non-meta message should be system
    if messages[0].get("role") != "system":
        issues.append(Issue("warning", "NO_SYSTEM_FIRST", "first message is not role=system"))

    return issues


# --- Semantic checks ---

def _tc_name(tc: dict) -> str | None:
    return (tc.get("function", {}) or {}).get("name")


def _tc_args(tc: dict) -> dict | None:
    args_str = (tc.get("function", {}) or {}).get("arguments")
    if not isinstance(args_str, str):
        return None
    try:
        return json.loads(args_str)
    except json.JSONDecodeError:
        return None


def check_semantic(example: dict, tools_by_name: dict[str, dict]) -> list[Issue]:
    issues: list[Issue] = []

    if "messages" not in example or "_error" in example:
        return []  # structural handles

    messages = example["messages"]
    if not isinstance(messages, list) or len(messages) < 2:
        return []

    mode = detect_mode(example)
    assistant_msgs = [(i, m) for i, m in enumerate(messages)
                      if isinstance(m, dict) and m.get("role") == "assistant"]

    # --- Validate ALL tool_call arguments against JSON Schema (any mode) ---
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        for j, tc in enumerate(m.get("tool_calls", []) or []):
            if not isinstance(tc, dict):
                continue
            name = _tc_name(tc)
            if name not in tools_by_name:
                continue  # structural handled UNKNOWN_TOOL
            args = _tc_args(tc)
            if args is None:
                continue  # structural handled bad JSON
            try:
                jsonschema.validate(args, tools_by_name[name])
            except jsonschema.ValidationError as e:
                issues.append(Issue("error", "ARGS_SCHEMA_FAIL",
                                    f"{name}: {e.message}",
                                    f"messages[{i}].tool_calls[{j}]"))

    if mode == "agent":
        issues.extend(_check_agent_mode(messages, assistant_msgs))
    elif mode == "agent_question":
        issues.extend(_check_question_mode(messages, assistant_msgs))
    elif mode == "plain":
        issues.extend(_check_plain_mode(messages, assistant_msgs))
    else:
        issues.append(Issue("warning", "UNKNOWN_MODE", f"unrecognized mode '{mode}'"))

    return issues


def _check_agent_mode(messages: list[dict], assistant_msgs: list[tuple[int, dict]]) -> list[Issue]:
    issues: list[Issue] = []

    if not assistant_msgs:
        issues.append(Issue("error", "NO_ASSISTANT", "agent mode has no assistant messages"))
        return issues

    # First assistant tool_call must be plan_write
    first_idx, first_msg = assistant_msgs[0]
    first_tcs = first_msg.get("tool_calls") or []
    if not first_tcs:
        issues.append(Issue("error", "AGENT_NO_FIRST_TOOL_CALL",
                            "first assistant message must contain a tool_call (plan_write)",
                            f"messages[{first_idx}]"))
    elif _tc_name(first_tcs[0]) != "plan_write":
        issues.append(Issue("error", "AGENT_FIRST_NOT_PLAN_WRITE",
                            f"first tool_call must be plan_write, got '{_tc_name(first_tcs[0])}'",
                            f"messages[{first_idx}].tool_calls[0]"))

    # Gather task_ids from state tool args
    task_ids: set[str] = set()
    for i, m in enumerate(messages):
        for j, tc in enumerate(m.get("tool_calls", []) or []):
            name = _tc_name(tc)
            if name in STATE_TOOLS:
                args = _tc_args(tc)
                if args is None:
                    continue
                if "task_id" in args:
                    task_ids.add(args["task_id"])
                else:
                    issues.append(Issue("error", "STATE_TOOL_NO_TASK_ID",
                                        f"{name} missing task_id argument",
                                        f"messages[{i}].tool_calls[{j}]"))
    if len(task_ids) > 1:
        issues.append(Issue("error", "MULTIPLE_TASK_IDS",
                            f"multiple task_ids in one example: {sorted(task_ids)}"))

    # Read-before-action: project tool requires prior step_read in current step
    # Reset triggers: step_update_result, plan_revise
    last_step_read: int | None = None
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        for j, tc in enumerate(m.get("tool_calls", []) or []):
            name = _tc_name(tc)
            if name == "step_read":
                args = _tc_args(tc) or {}
                last_step_read = args.get("step_n")
            elif name in PROJECT_TOOLS:
                if last_step_read is None:
                    issues.append(Issue("error", "PROJECT_TOOL_NO_STEP_READ",
                                        f"{name} called without prior step_read in the current step window",
                                        f"messages[{i}].tool_calls[{j}]"))
            elif name == "step_update_result":
                last_step_read = None
            elif name == "plan_revise":
                last_step_read = None

    # SELF-CHECK presence: >= half of assistant messages should have it
    self_check = sum(1 for _, m in assistant_msgs if "SELF-CHECK" in (m.get("content") or ""))
    if self_check < len(assistant_msgs) / 2:
        issues.append(Issue("warning", "LOW_SELF_CHECK_RATE",
                            f"only {self_check}/{len(assistant_msgs)} assistant messages have SELF-CHECK"))

    # THOUGHT presence: same check
    thought = sum(1 for _, m in assistant_msgs if "THOUGHT:" in (m.get("content") or ""))
    if thought < len(assistant_msgs) / 2:
        issues.append(Issue("warning", "LOW_THOUGHT_RATE",
                            f"only {thought}/{len(assistant_msgs)} assistant messages have THOUGHT"))

    return issues


def _check_question_mode(messages: list[dict], assistant_msgs: list[tuple[int, dict]]) -> list[Issue]:
    issues: list[Issue] = []
    if len(assistant_msgs) != 1:
        issues.append(Issue("warning", "QUESTION_MULTIPLE_ASSISTANT",
                            f"agent_question expected 1 assistant message, got {len(assistant_msgs)}"))
    for i, m in assistant_msgs:
        if m.get("tool_calls"):
            issues.append(Issue("error", "QUESTION_HAS_TOOL_CALLS",
                                "agent_question must not have tool_calls",
                                f"messages[{i}]"))
        if "QUESTION:" not in (m.get("content") or ""):
            issues.append(Issue("error", "QUESTION_NO_MARKER",
                                "agent_question must contain 'QUESTION:' marker",
                                f"messages[{i}]"))
    return issues


def _check_plain_mode(messages: list[dict], assistant_msgs: list[tuple[int, dict]]) -> list[Issue]:
    issues: list[Issue] = []
    for i, m in assistant_msgs:
        if m.get("tool_calls"):
            issues.append(Issue("error", "PLAIN_HAS_TOOL_CALLS",
                                "plain mode must not have tool_calls",
                                f"messages[{i}]"))
        content = m.get("content") or ""
        for mk in AGENT_MARKERS:
            if mk in content:
                issues.append(Issue("warning", "PLAIN_HAS_AGENT_MARKER",
                                    f"plain mode assistant contains agent marker '{mk}'",
                                    f"messages[{i}]"))
    return issues


# --- Dedup (exact match only for now; embeddings later) ---

def check_dedup(examples: list[tuple[str, dict]]) -> list[Issue]:
    issues: list[Issue] = []
    seen: dict[str, str] = {}
    for src_id, ex in examples:
        msgs = ex.get("messages", [])
        if not isinstance(msgs, list):
            continue
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "user":
                txt = (m.get("content") or "").strip()
                if not txt:
                    continue
                if txt in seen:
                    issues.append(Issue("warning", "DUP_USER_TEXT",
                                        f"{src_id} duplicates first user text of {seen[txt]}"))
                else:
                    seen[txt] = src_id
                break  # compare only first user message
    return issues


# --- Reporting ---

def print_report(
    results: list[tuple[str, list[Issue], str]],
    dedup: list[Issue],
    verbose: bool = True,
) -> int:
    total_errors = 0
    total_warnings = 0
    mode_counts: dict[str, int] = {}

    for src_id, issues, mode in results:
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        errs = [x for x in issues if x.severity == "error"]
        warns = [x for x in issues if x.severity == "warning"]
        total_errors += len(errs)
        total_warnings += len(warns)
        status = "OK  " if not errs else "FAIL"
        print(f"[{status}] {src_id}  mode={mode}  errors={len(errs)}  warnings={len(warns)}")
        if verbose or errs:
            for iss in issues:
                tag = "ERR " if iss.severity == "error" else "warn"
                path = f" @ {iss.path}" if iss.path else ""
                print(f"    {tag} {iss.code}{path}: {iss.message}")

    if dedup:
        print("\n--- Cross-example dedup ---")
        for iss in dedup:
            print(f"    warn {iss.code}: {iss.message}")
        total_warnings += len(dedup)

    print("\n=== Summary ===")
    print(f"  examples: {len(results)}")
    print(f"  by mode:  {mode_counts}")
    print(f"  errors:   {total_errors}")
    print(f"  warnings: {total_warnings}")
    return total_errors


# --- CLI ---

def main() -> int:
    ap = argparse.ArgumentParser(description="Validate fine-tune dataset examples")
    ap.add_argument("path", type=Path, help="File (.json/.jsonl) or directory of .json files")
    ap.add_argument("--contracts", type=Path,
                    default=Path(__file__).resolve().parent.parent.parent / "data" / "contracts",
                    help="Path to contracts directory")
    ap.add_argument("-q", "--quiet", action="store_true", help="Show only failures")
    args = ap.parse_args()

    if not args.path.exists():
        print(f"error: path not found: {args.path}", file=sys.stderr)
        return 2

    tools_by_name = load_tool_schemas(args.contracts)
    examples = load_examples(args.path)

    if not examples:
        print(f"warning: no examples loaded from {args.path}", file=sys.stderr)
        return 1

    results: list[tuple[str, list[Issue], str]] = []
    for src_id, ex in examples:
        issues: list[Issue] = []
        issues.extend(check_structural(ex))
        issues.extend(check_semantic(ex, tools_by_name))
        mode = detect_mode(ex) if "_error" not in ex else "?"
        results.append((src_id, issues, mode))

    dedup = check_dedup(examples)
    total_errors = print_report(results, dedup, verbose=not args.quiet)
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
