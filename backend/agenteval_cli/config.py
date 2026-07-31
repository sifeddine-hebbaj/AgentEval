"""agenteval.yaml schema and loader."""
from __future__ import annotations

from typing import Optional

import yaml
from pydantic import BaseModel, Field


class GateConfig(BaseModel):
    mode: str = "block"  # block | warn
    min_mean_score: dict[str, float] = Field(default_factory=dict)
    max_regression_delta: float = 0.05
    critical_tags: list[str] = Field(default_factory=list)
    max_p95_latency_ms: Optional[int] = None
    max_total_cost_usd: Optional[float] = None


class ScorerConfig(BaseModel):
    name: str
    type: str  # a registered scorer name, e.g. "exact_match", "llm_judge"
    weight: float = 1.0
    is_critical: bool = False
    config: dict = Field(default_factory=dict)


class AgentEvalConfig(BaseModel):
    project: str
    dataset: str
    runner: str
    scorers: list[ScorerConfig] = Field(default_factory=list)
    gate: GateConfig = Field(default_factory=GateConfig)
    baseline: Optional[str] = None
    base_url: str = "http://localhost:8000"

    @classmethod
    def from_yaml(cls, path: str) -> "AgentEvalConfig":
        with open(path, "r", encoding="utf-8") as f:
            try:
                raw = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                raise ValueError(f"{path}: invalid YAML ({exc})") from exc
        if raw is None:
            raise ValueError(f"{path}: file is empty")
        try:
            return cls(**raw)
        except Exception as exc:
            raise ValueError(f"{path}: invalid agenteval.yaml ({exc})") from exc
