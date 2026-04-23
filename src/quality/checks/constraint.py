"""Constraint-based check — deterministic validation, zero API calls.

Reuses validate_gold() from the dataset validator and adds domain-specific
invariants on top.
"""

from __future__ import annotations

import time

from src.validator.validate import validate_gold
from src.quality.models import CheckVerdict


def _check_invariants(extraction: dict) -> list[str]:
    """Domain-specific invariants beyond schema validation."""
    warnings: list[str] = []

    title = extraction.get("title", "")
    if isinstance(title, str):
        if len(title) < 5:
            warnings.append(f"title слишком короткий ({len(title)} символов)")
        if len(title) > 200:
            warnings.append(f"title слишком длинный ({len(title)} символов)")

    typ = extraction.get("type")
    modules = extraction.get("modules", [])
    new_modules = extraction.get("newModules", [])

    # feat/refactor обычно затрагивает хотя бы один модуль
    if typ in ("feat", "refactor") and not modules and not new_modules:
        warnings.append(f"type={typ}, но modules и newModules пусты")

    # feat обычно имеет acceptanceCriteria
    ac = extraction.get("acceptanceCriteria", [])
    if typ == "feat" and not ac:
        warnings.append("type=feat, но acceptanceCriteria пуст")

    return warnings


def run(extraction: dict, **_kwargs) -> CheckVerdict:
    """Run constraint-based check on extraction result.

    Returns:
        CheckVerdict with status FAIL/UNSURE/OK.
        - FAIL: schema errors (validate_gold found problems)
        - UNSURE: schema OK but domain invariants violated
        - OK: everything checks out
    """
    t0 = time.perf_counter()

    schema_errors = validate_gold(extraction, "constraint")
    invariant_warnings = _check_invariants(extraction)

    latency = (time.perf_counter() - t0) * 1000

    if schema_errors:
        return CheckVerdict(
            check_name="constraint",
            status="FAIL",
            details={"schema_errors": schema_errors,
                     "invariant_warnings": invariant_warnings},
            latency_ms=latency,
        )

    if invariant_warnings:
        return CheckVerdict(
            check_name="constraint",
            status="UNSURE",
            details={"schema_errors": [],
                     "invariant_warnings": invariant_warnings},
            latency_ms=latency,
        )

    return CheckVerdict(
        check_name="constraint",
        status="OK",
        details={"schema_errors": [], "invariant_warnings": []},
        latency_ms=latency,
    )
