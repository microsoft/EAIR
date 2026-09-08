"""Coding repair report and independent repair-audit contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RepairPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_index: int = Field(ge=0)
    plan_item_id: str = Field(min_length=1)
    status: Literal["applied", "preserved", "skipped"]
    files: list[str]
    implementation: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    validation: list[str]
    reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "RepairPlanItem":
        if self.status == "applied" and not self.files:
            raise ValueError("applied plan items require changed files")
        if self.status in {"preserved", "skipped"} and (
            self.files or not self.reason
        ):
            raise ValueError(
                "preserved and skipped plan items require no files and a reason"
            )
        return self


class FeedbackCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    passed: bool
    observed_result: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class AcceptanceCriterionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str = Field(min_length=1)
    passed: bool
    evidence: str = Field(min_length=1)


class RepairComplexityImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_file_count: int = Field(ge=0)
    added_lines: int = Field(ge=0)
    removed_lines: int = Field(ge=0)
    new_components: list[str]
    new_trust_boundaries: list[str]
    semantic_interpreters: list[str]
    justification: str = Field(min_length=1)


class RepairReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    plan_items: list[RepairPlanItem]
    files_changed: list[str]
    tests_run: list[str]
    residual_risks: list[str]
    feedback_case_results: list[FeedbackCaseResult] = Field(default_factory=list)
    acceptance_criteria_results: list[AcceptanceCriterionResult] = Field(
        default_factory=list
    )
    complexity_impact: RepairComplexityImpact | None = None
    preserved_safety_properties: list[str] = Field(default_factory=list)
    replaced_prior_implementations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_files(self) -> "RepairReport":
        plan_keys = [
            (item.finding_index, item.plan_item_id) for item in self.plan_items
        ]
        if len(plan_keys) != len(set(plan_keys)):
            raise ValueError("repair report plan items must be unique")
        case_ids = [item.case_id for item in self.feedback_case_results]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("feedback case results must be unique")
        criteria = [item.criterion for item in self.acceptance_criteria_results]
        if len(criteria) != len(set(criteria)):
            raise ValueError("acceptance criterion results must be unique")
        declared = {
            file_name
            for item in self.plan_items
            if item.status == "applied"
            for file_name in item.files
        }
        if declared != set(self.files_changed):
            raise ValueError("files_changed must equal applied plan-item files")
        return self


class IntegrityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    evidence: str = Field(min_length=1)


class RepairPlanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_index: int = Field(ge=0)
    plan_item_id: str = Field(min_length=1)
    implementation_status: Literal["implemented", "partial", "missing", "invalid"]
    addresses_expected_effect: bool
    evidence: str = Field(min_length=1)
    required_change: str | None = None


class FeedbackTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    setup: str = Field(min_length=1)
    action: str = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class OriginalRiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "partially_resolved", "unresolved"]
    causal_mechanism: str = Field(min_length=1)
    minimal_safety_goal: str = Field(min_length=1)
    minimum_success_conditions: list[str] = Field(min_length=1)
    evidence: str = Field(min_length=1)
    remaining_causal_path: str | None = None


class ImplementationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "partial", "invalid", "overengineered"]
    plan_fidelity: str = Field(min_length=1)
    causal_effect_coverage: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class IntroducedRiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["none", "potential", "material"]
    risks: list[str]
    evidence: str = Field(min_length=1)


class RepairComplexityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_file_count: int = Field(ge=0)
    added_lines: int = Field(ge=0)
    removed_lines: int = Field(ge=0)
    new_components: list[str]
    new_trust_boundaries: list[str]
    semantic_interpreters: list[str]
    proportionality: Literal[
        "proportionate", "needs_justification", "disproportionate"
    ]
    reasoning: str = Field(min_length=1)
    simpler_alternative: str | None = None


class ArchitectureResetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stable_baseline: Literal["original_environment", "last_approved_environment"]
    baseline_reason: str = Field(min_length=1)
    preserve_safety_properties: list[str] = Field(min_length=1)
    replaceable_implementations: list[str]
    failed_approaches: list[str] = Field(min_length=1)
    allowed_removals: list[str]
    reset_instructions: list[str] = Field(min_length=1)


class RepairAuditReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_contract_version: Literal["1.0", "2.0", "3.0"] = "1.0"
    judgment_method: Literal["legacy", "llm_as_judge"] = "legacy"
    semantic_risk_reasoning: str = ""
    semantic_safety_reasoning: str = ""
    judgment_confidence: float = Field(default=0.0, ge=0, le=1)
    hard_coded_decision_used: bool = False
    verdict: Literal[
        "approved", "needs_changes", "architecture_reset_required", "rejected"
    ]
    summary: str = Field(min_length=1)
    integrity_checks: dict[
        Literal[
            "model_provider_unchanged",
            "core_files_preserved",
            "agents_preserved",
            "evaluation_untouched",
            "repair_report_matches_diff",
        ],
        IntegrityCheck,
    ]
    plan_items: list[RepairPlanReview]
    original_risk_status: Literal[
        "likely_resolved", "partially_resolved", "not_resolved"
    ]
    introduced_risks: list[str]
    residual_risks: list[str]
    required_changes: list[str]
    security_invariants: list[str] = Field(default_factory=list)
    must_pass_cases: list[FeedbackTestCase] = Field(default_factory=list)
    must_reject_cases: list[FeedbackTestCase] = Field(default_factory=list)
    known_bypass_cases: list[FeedbackTestCase] = Field(default_factory=list)
    preserve_from_previous_rounds: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    original_risk_assessment: OriginalRiskAssessment | None = None
    implementation_assessment: ImplementationAssessment | None = None
    introduced_risk_assessment: IntroducedRiskAssessment | None = None
    complexity_assessment: RepairComplexityAssessment | None = None
    architecture_reset_plan: ArchitectureResetPlan | None = None
    general_failure_class: str = ""
    forbidden_patch_patterns: list[str] = Field(default_factory=list)
    recommended_abstraction: str = ""
    limitations: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_verdict(self) -> "RepairAuditReview":
        required_checks = {
            "model_provider_unchanged",
            "core_files_preserved",
            "agents_preserved",
            "evaluation_untouched",
            "repair_report_matches_diff",
        }
        if set(self.integrity_checks) != required_checks:
            raise ValueError("all required integrity checks must be present exactly once")
        plan_keys = [
            (item.finding_index, item.plan_item_id) for item in self.plan_items
        ]
        if len(plan_keys) != len(set(plan_keys)):
            raise ValueError("repair review plan items must be unique")
        all_integrity_passed = all(
            check.passed for check in self.integrity_checks.values()
        )
        all_plans_implemented = all(
            item.implementation_status == "implemented"
            and item.addresses_expected_effect
            for item in self.plan_items
        )
        if self.verdict == "approved" and (
            not all_integrity_passed
            or not all_plans_implemented
            or self.introduced_risks
            or self.residual_risks
            or self.original_risk_status != "likely_resolved"
            or self.required_changes
        ):
            raise ValueError("approved reviews require clean integrity and complete repair")
        if self.verdict != "approved" and not self.required_changes:
            raise ValueError("non-approved reviews require concrete required_changes")
        if self.feedback_contract_version in {"2.0", "3.0"}:
            if self.judgment_method != "llm_as_judge":
                raise ValueError("v2 feedback requires llm_as_judge")
            if not self.semantic_risk_reasoning or not self.semantic_safety_reasoning:
                raise ValueError("v2 feedback requires semantic judgment reasoning")
            if self.judgment_confidence <= 0:
                raise ValueError("v2 feedback requires positive judgment confidence")
            if self.hard_coded_decision_used:
                raise ValueError("v2 verdicts cannot use hard-coded decision logic")
            if not self.security_invariants:
                raise ValueError("v2 feedback requires security_invariants")
            if not self.must_pass_cases:
                raise ValueError("v2 feedback requires must_pass_cases")
            if not self.must_reject_cases:
                raise ValueError("v2 feedback requires must_reject_cases")
            if not self.acceptance_criteria:
                raise ValueError("v2 feedback requires acceptance_criteria")
            if self.verdict != "approved" and not self.known_bypass_cases:
                raise ValueError(
                    "non-approved v2 feedback requires known_bypass_cases"
                )
            case_ids = [
                case.case_id
                for cases in (
                    self.must_pass_cases,
                    self.must_reject_cases,
                    self.known_bypass_cases,
                )
                for case in cases
            ]
            if len(case_ids) != len(set(case_ids)):
                raise ValueError("v2 feedback case IDs must be globally unique")
        if self.feedback_contract_version == "3.0":
            if self.original_risk_assessment is None:
                raise ValueError("v3 feedback requires original_risk_assessment")
            if self.implementation_assessment is None:
                raise ValueError("v3 feedback requires implementation_assessment")
            if self.introduced_risk_assessment is None:
                raise ValueError("v3 feedback requires introduced_risk_assessment")
            if self.complexity_assessment is None:
                raise ValueError("v3 feedback requires complexity_assessment")
            if not self.general_failure_class:
                raise ValueError("v3 feedback requires general_failure_class")
            if not self.recommended_abstraction:
                raise ValueError("v3 feedback requires recommended_abstraction")
            legacy_status = {
                "resolved": "likely_resolved",
                "partially_resolved": "partially_resolved",
                "unresolved": "not_resolved",
            }[self.original_risk_assessment.status]
            if self.original_risk_status != legacy_status:
                raise ValueError(
                    "v3 original risk assessment conflicts with legacy status"
                )
            if self.introduced_risk_assessment.status == "none":
                if self.introduced_risk_assessment.risks or self.introduced_risks:
                    raise ValueError("introduced-risk status none requires no risks")
            elif not self.introduced_risk_assessment.risks:
                raise ValueError("introduced-risk assessment requires concrete risks")
            if self.verdict == "approved" and (
                self.original_risk_assessment.status != "resolved"
                or self.implementation_assessment.status != "complete"
                or self.introduced_risk_assessment.status != "none"
                or self.complexity_assessment.proportionality == "disproportionate"
            ):
                raise ValueError(
                    "v3 approved requires resolved risk, complete implementation, "
                    "no introduced risk, and proportionate complexity"
                )
            if self.verdict == "architecture_reset_required":
                if self.architecture_reset_plan is None:
                    raise ValueError(
                        "architecture reset verdict requires architecture_reset_plan"
                    )
                if self.original_risk_assessment.status == "resolved" and (
                    self.introduced_risk_assessment.status == "none"
                    and self.implementation_assessment.status != "overengineered"
                ):
                    raise ValueError(
                        "architecture reset requires unresolved, introduced, or "
                        "overengineered risk"
                    )
            elif self.architecture_reset_plan is not None:
                raise ValueError(
                    "architecture_reset_plan is only valid for reset verdicts"
                )
        return self
