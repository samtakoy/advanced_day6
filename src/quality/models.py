"""Data models for quality control pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CheckVerdict:
    """Result of a single confidence check."""
    check_name: str           # "constraint" | "redundancy" | "scoring"
    status: str               # "OK" | "UNSURE" | "FAIL"
    details: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    extra_calls: int = 0      # additional API calls made
    extra_tokens_in: int = 0
    extra_tokens_out: int = 0


@dataclass
class PipelineResult:
    """Result of the full quality pipeline for one example."""
    name: str
    final_extraction: dict | None = None
    status: str = "PENDING"   # "ACCEPTED" | "ACCEPTED_WITH_WARNINGS" | "REJECTED"
    attempts: int = 1         # 1 = first try worked
    verdicts: list[CheckVerdict] = field(default_factory=list)
    total_latency_ms: float = 0.0
    total_api_calls: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    # baseline metrics if gold is available
    baseline_metrics: dict | None = None
    error: str | None = None


@dataclass
class PipelineConfig:
    """Configuration for the quality pipeline."""
    checks: list[str] = field(default_factory=lambda: ["constraint", "redundancy", "scoring"])
    max_retries: int = 2
    redundancy_n: int = 3
    redundancy_temperature: float = 0.7
    scoring_temperature: float = 0.0
