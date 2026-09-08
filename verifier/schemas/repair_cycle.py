"""Persistent records for bounded iterative repair conversations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RepairCycleIteration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iteration: int = Field(ge=1, le=5)
    input_environment: str = Field(min_length=1)
    output_environment: str = Field(min_length=1)
    coder_task: str = Field(min_length=1)
    coder_trial: str = Field(min_length=1)
    coder_trajectory: str = Field(min_length=1)
    repair_report: str = Field(min_length=1)
    auditor_task: str = Field(min_length=1)
    auditor_trial: str = Field(min_length=1)
    auditor_trajectory: str = Field(min_length=1)
    feedback_report: str = Field(min_length=1)
    verdict: Literal[
        "approved", "needs_changes", "architecture_reset_required", "rejected"
    ]
    original_risk_status: Literal[
        "likely_resolved", "partially_resolved", "not_resolved"
    ]
    changed_files: list[str]
    required_changes: list[str]
    architecture_reset_applied: bool = False
    reset_baseline: str | None = None
    implementation_status: Literal[
        "complete", "partial", "invalid", "overengineered"
    ] | None = None
    introduced_risk_status: Literal["none", "potential", "material"] | None = None
    general_failure_class: str = ""


class RepairCycleEnvironmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(min_length=1)
    max_iterations: int = Field(default=5, ge=1, le=5)
    iterations: list[RepairCycleIteration] = Field(min_length=1, max_length=5)
    total_repair_attempts: int = Field(ge=1, le=5)
    repaired: bool
    final_status: Literal[
        "approved", "rejected", "max_iterations_needs_changes", "error"
    ]
    final_environment: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result(self) -> "RepairCycleEnvironmentResult":
        if self.total_repair_attempts != len(self.iterations):
            raise ValueError("total_repair_attempts must equal iteration count")
        expected_iterations = list(range(1, len(self.iterations) + 1))
        if [item.iteration for item in self.iterations] != expected_iterations:
            raise ValueError("repair iterations must be contiguous from one")
        if self.repaired != (self.final_status == "approved"):
            raise ValueError("repaired must match approved final status")
        if self.repaired and self.iterations[-1].verdict != "approved":
            raise ValueError("repaired cycles require an approved final review")
        if len(self.iterations) == self.max_iterations:
            if (
                self.iterations[-1].verdict in {
                    "needs_changes", "architecture_reset_required"
                }
                and self.final_status != "max_iterations_needs_changes"
            ):
                raise ValueError("unresolved final iteration must record max-iteration stop")
        return self


class RepairCycleRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    max_iterations: int = Field(default=5, ge=1, le=5)
    environments: list[RepairCycleEnvironmentResult]
    total_repair_attempts: int = Field(ge=0)
    repaired_environments: int = Field(ge=0)
    unresolved_environments: int = Field(ge=0)
    local_environment_modified: bool
    behavioral_episode_retest_run: bool

    @model_validator(mode="after")
    def validate_totals(self) -> "RepairCycleRunResult":
        if self.total_repair_attempts != sum(
            item.total_repair_attempts for item in self.environments
        ):
            raise ValueError("total repair-attempt count is inconsistent")
        repaired = sum(item.repaired for item in self.environments)
        if self.repaired_environments != repaired:
            raise ValueError("repaired environment count is inconsistent")
        if self.unresolved_environments != len(self.environments) - repaired:
            raise ValueError("unresolved environment count is inconsistent")
        return self
