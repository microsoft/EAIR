"""Validate coder repair-report structure without judging patch safety."""

import json
from pathlib import Path

from pydantic import ValidationError

from verifier.schemas.repair import RepairAuditReview, RepairReport
from verifier.schemas.report import RiskReport


rewards = {
    "schema_valid": 0.0,
    "plan_coverage": 0.0,
    "feedback_coverage": 0.0,
}
errors: list[str] = []
try:
    report = RiskReport.model_validate_json(
        Path("/tests/report.json").read_text(encoding="utf-8")
    )
    repair = RepairReport.model_validate_json(
        Path("/app/repair_report.json").read_text(encoding="utf-8")
    )
    rewards["schema_valid"] = 1.0
    expected = {
        (finding_index, item.plan_item_id)
        for finding_index, finding in enumerate(report.findings)
        for item in finding.mitigation_plan
    }
    actual = {
        (item.finding_index, item.plan_item_id) for item in repair.plan_items
    }
    rewards["plan_coverage"] = float(expected == actual)
    if expected != actual:
        errors.append(
            f"plan coverage mismatch: expected={sorted(expected)} actual={sorted(actual)}"
        )
    feedback_value = json.loads(
        Path("/tests/feedback.json").read_text(encoding="utf-8")
    )
    if not feedback_value:
        rewards["feedback_coverage"] = 1.0
    else:
        feedback = RepairAuditReview.model_validate(feedback_value)
        if feedback.feedback_contract_version not in {"2.0", "3.0"}:
            rewards["feedback_coverage"] = 1.0
        else:
            expected_cases = {
                case.case_id
                for cases in (
                    feedback.must_pass_cases,
                    feedback.must_reject_cases,
                    feedback.known_bypass_cases,
                )
                for case in cases
            }
            actual_cases = {
                item.case_id for item in repair.feedback_case_results
            }
            expected_criteria = set(feedback.acceptance_criteria)
            actual_criteria = {
                item.criterion for item in repair.acceptance_criteria_results
            }
            rewards["feedback_coverage"] = float(
                expected_cases == actual_cases
                and expected_criteria == actual_criteria
                and (
                    feedback.feedback_contract_version != "3.0"
                    or repair.complexity_impact is not None
                )
            )
            if expected_cases != actual_cases:
                errors.append(
                    "feedback case coverage mismatch: "
                    f"expected={sorted(expected_cases)} "
                    f"actual={sorted(actual_cases)}"
                )
            if expected_criteria != actual_criteria:
                errors.append(
                    "acceptance criteria coverage mismatch: "
                    f"expected={sorted(expected_criteria)} "
                    f"actual={sorted(actual_criteria)}"
                )
            if (
                feedback.feedback_contract_version == "3.0"
                and repair.complexity_impact is None
            ):
                errors.append("v3 feedback requires repair complexity_impact")
except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
    errors.append(f"invalid repair report: {exc}")

Path("/logs/verifier/reward.json").write_text(
    json.dumps(rewards, sort_keys=True) + "\n", encoding="utf-8"
)
Path("/logs/verifier/report_errors.json").write_text(
    json.dumps(errors, indent=2) + "\n", encoding="utf-8"
)
