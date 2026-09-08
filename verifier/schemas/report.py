"""Auditor report contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from verifier.schemas.operators import validate_operator_params


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_ids: list[str] = Field(min_length=1)
    edge_refs: list[str] = Field(default_factory=list)
    quote: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1)


class PlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_item_id: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    params: dict
    target: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)
    safety_invariant: str = ""
    minimum_success_conditions: list[str] = Field(default_factory=list)
    implementation_flexibility: str = ""

    @model_validator(mode="after")
    def validate_operator(self) -> "PlanItem":
        validate_operator_params(self.operator, self.params)
        return self


class RiskFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_description: str = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)
    involved_agents: list[str] = Field(min_length=1)
    propagation_path: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)
    mitigation_plan: list[PlanItem] = Field(min_length=1, max_length=5)


class RiskReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str = Field(min_length=1)
    risk_detected: bool
    findings: list[RiskFinding]
    clean_rationale: str | None = None
    auditor_version: str = Field(min_length=1)
    graph_snapshot_path: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_detection_decision(self) -> "RiskReport":
        if self.risk_detected != bool(self.findings):
            raise ValueError("risk_detected must equal bool(findings)")
        if self.risk_detected and self.clean_rationale is not None:
            raise ValueError("clean_rationale must be null when risk is detected")
        if not self.risk_detected and not self.clean_rationale:
            raise ValueError("clean_rationale is required for a clean report")
        return self
