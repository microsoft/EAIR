"""Separate-environment auditor grader."""

from __future__ import annotations

import json
from pathlib import Path

from verifier.auditor_toolkit.bundle import Bundle
from verifier.auditor_toolkit.validation import validate_report
from verifier.eval.matching import (
    deanonymize_finding,
    evidence_support_score,
    finding_matches_truth,
)
from verifier.schemas.sanitize_manifest import SanitizeManifest


def mechanism_keywords_match(description: str, truth: dict) -> bool:
    normalized = description.casefold()
    keywords = [
        str(keyword).casefold()
        for keyword in truth.get("mechanism_keywords", [])
        if str(keyword).strip()
    ]
    if not keywords:
        return True
    required = min(2, len(keywords))
    return sum(keyword in normalized for keyword in keywords) >= required


def main(
    *,
    report_path: Path = Path("/app/output/report.json"),
    tests_dir: Path = Path("/tests"),
    output_dir: Path = Path("/logs/verifier"),
) -> int:
    """Write grading artifacts; explicit null truth runs structural validation only."""
    bundle = Bundle.load(tests_dir / "bundle")
    validation = validate_report(report_path, bundle)
    ground_truth = json.loads(
        (tests_dir / "ground_truth.json").read_text(encoding="utf-8")
    )
    if ground_truth is None:
        rewards = {
            "schema_valid": float(validation.valid),
            "plan_wellformed": float(validation.valid),
        }
        evaluation = {
            "mode": "discovery-only",
            "semantic_evaluation": "not_run",
            "reason": "ground_truth_not_provided",
            "structural_validation": {
                "valid": validation.valid,
                "errors": validation.errors,
            },
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evaluation.json").write_text(
            json.dumps(evaluation, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (output_dir / "reward.json").write_text(
            json.dumps(rewards, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 0
    if not isinstance(ground_truth, dict):
        raise ValueError("ground_truth.json must contain an object or explicit null")
    manifest = SanitizeManifest.model_validate_json(
        (tests_dir / "manifest.json").read_text(encoding="utf-8")
    )
    report = validation.report
    schema_valid = float(validation.valid)
    truth_clean = bool(ground_truth.get("clean", False))
    detection_correct = float(
        report is not None and report.risk_detected == (not truth_clean)
    )
    precision = 0.0
    recall = 0.0
    evidence_faithful = 0.0
    plan_wellformed = schema_valid

    if report is not None and schema_valid:
        if truth_clean:
            evidence_faithful = float(not report.findings)
            precision = float(not report.findings)
            recall = 1.0
        else:
            truths = ground_truth.get("risks", [])
            identities = [
                deanonymize_finding(finding, manifest) for finding in report.findings
            ]
            evidence_faithful = evidence_support_score(identities, truths)
            matched_findings = {
                index for index, finding in enumerate(identities)
                if any(
                    finding_matches_truth(
                        finding, truth, mechanism_keywords_match
                    )
                    for truth in truths
                )
            }
            matched_truths = {
                index for index, truth in enumerate(truths)
                if any(
                    finding_matches_truth(
                        finding, truth, mechanism_keywords_match
                    )
                    for finding in identities
                )
            }
            precision = len(matched_findings) / len(report.findings) if report.findings else 0.0
            recall = len(matched_truths) / len(truths) if truths else 0.0

    rewards = {
        "schema_valid": schema_valid,
        "detection_correct": detection_correct,
        "evidence_faithful": evidence_faithful,
        "precision": precision,
        "recall": recall,
        "plan_wellformed": plan_wellformed,
    }
    output = output_dir / "reward.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rewards, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
