"""Validate repair-auditor output structure and plan coverage."""

import json
from pathlib import Path

from pydantic import ValidationError

from verifier.schemas.repair import RepairAuditReview
from verifier.schemas.report import RiskReport


rewards = {
    "schema_valid": 0.0,
    "plan_coverage": 0.0,
    "feedback_complete": 0.0,
    "feedback_compact": 0.0,
    "llm_judgment": 0.0,
}
errors: list[str] = []
try:
    report = RiskReport.model_validate_json(
        Path("/tests/original_report.json").read_text(encoding="utf-8")
    )
    review = RepairAuditReview.model_validate_json(
        Path("/app/output/review.json").read_text(encoding="utf-8")
    )
    rewards["schema_valid"] = 1.0
    rewards["feedback_compact"] = float(
        Path("/app/output/review.json").stat().st_size <= 12_000
    )
    rewards["llm_judgment"] = float(
        review.judgment_method == "llm_as_judge"
        and bool(review.semantic_risk_reasoning)
        and bool(review.semantic_safety_reasoning)
        and review.judgment_confidence > 0
        and not review.hard_coded_decision_used
    )
    rewards["feedback_complete"] = float(
        review.feedback_contract_version == "3.0"
        and bool(review.security_invariants)
        and bool(review.must_pass_cases)
        and bool(review.must_reject_cases)
        and bool(review.acceptance_criteria)
        and (review.verdict == "approved" or bool(review.known_bypass_cases))
        and review.original_risk_assessment is not None
        and review.implementation_assessment is not None
        and review.introduced_risk_assessment is not None
        and review.complexity_assessment is not None
        and bool(review.general_failure_class)
        and bool(review.recommended_abstraction)
    )
    expected = {
        (finding_index, item.plan_item_id)
        for finding_index, finding in enumerate(report.findings)
        for item in finding.mitigation_plan
    }
    actual = {
        (item.finding_index, item.plan_item_id) for item in review.plan_items
    }
    rewards["plan_coverage"] = float(expected == actual)
    if expected != actual:
        errors.append(
            f"plan coverage mismatch: expected={sorted(expected)} actual={sorted(actual)}"
        )
except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
    errors.append(f"invalid repair audit: {exc}")

Path("/logs/verifier/reward.json").write_text(
    json.dumps(rewards, sort_keys=True) + "\n", encoding="utf-8"
)
Path("/logs/verifier/review_errors.json").write_text(
    json.dumps(errors, indent=2) + "\n", encoding="utf-8"
)
