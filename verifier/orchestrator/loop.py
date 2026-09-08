"""Bounded detect-mitigate-retest control loop."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from verifier.auditor_toolkit.bundle import Bundle
from verifier.auditor_toolkit.validation import validate_report
from verifier.eval.splits import assert_template_frozen, content_digest
from verifier.exporter import export_episode_bundle
from verifier.orchestrator.materialize import (
    materialize_auditor_task,
    materialize_coder_task,
    materialize_repair_auditor_task,
)
from verifier.orchestrator.pipeline import (
    TRAPI_AGENT,
    TRAPI_AGENT_KWARGS,
    TRAPI_ALLOWED_HOSTS,
    TRAPI_API_BASE,
    RunRecord,
    run_harbor,
)
from verifier.schemas.report import RiskReport
from verifier.schemas.repair import RepairAuditReview
from verifier.schemas.sanitize_manifest import SanitizeManifest


@dataclass(frozen=True)
class AuditCase:
    case_id: str
    environment_id: str
    bundle_dir: Path
    manifest_path: Path | None = None
    risk_id: str | None = None


@dataclass(frozen=True)
class AuditOutcome:
    case: AuditCase
    report: RiskReport
    utility: float | None = None
    run_record: RunRecord | None = None


@dataclass
class RoundRecord:
    round_index: int
    environments: dict[str, Path]
    outcomes: list[AuditOutcome]
    modified_environments: dict[str, Path] = field(default_factory=dict)
    auditor_runs: list[RunRecord] = field(default_factory=list)
    coder_runs: list[RunRecord] = field(default_factory=list)
    repair_auditor_runs: list[RunRecord] = field(default_factory=list)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    report_paths: dict[str, Path] = field(default_factory=dict)
    repair_report_paths: dict[str, Path] = field(default_factory=dict)
    repair_review_paths: dict[str, Path] = field(default_factory=dict)
    verification_results: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class LoopResult:
    rounds: list[RoundRecord]
    stopped_clean: bool
    summary_path: Path | None = None


ExportCases = Callable[[dict[str, Path], int], Sequence[AuditCase]]
AuditCases = Callable[[Sequence[AuditCase], int], Sequence[AuditOutcome]]
MitigateEnvironments = Callable[
    [dict[str, Path], Sequence[AuditOutcome], int], dict[str, Path]
]
RerunEnvironments = Callable[[dict[str, Path], int], dict[str, Path]]


@dataclass(frozen=True)
class EpisodeTrial:
    case_id: str
    risk_id: str
    environment_id: str
    episode_dir: Path
    ground_truth: dict[str, Any]
    cohort: Literal["baseline", "same_seed", "fresh_seed", "perturbed"] = "baseline"
    utility: float | None = None


@dataclass(frozen=True)
class HarborLoopConfig:
    runs_root: Path
    auditor_agent: str
    auditor_model: str
    coder_agent: str
    coder_model: str
    smoke_commands: dict[str, list[str]]
    utility_commands: dict[str, list[str]]
    n_concurrent: int = 1
    sanitizer_version: str = "1"
    agent_allowed_hosts: tuple[str, ...] = TRAPI_ALLOWED_HOSTS
    harbor_executable: str = "harbor"
    agent_kwargs: dict[str, str] = field(
        default_factory=lambda: dict(TRAPI_AGENT_KWARGS)
    )
    agent_process_env: dict[str, str] = field(default_factory=dict)
    environment_splits: dict[str, Literal["dev", "held_out"]] = field(
        default_factory=dict
    )
    frozen_auditor_digest: str | None = None


ProduceTrials = Callable[[dict[str, Path], int], Sequence[EpisodeTrial]]


def auditor_surface_digest() -> str:
    verifier_root = Path(__file__).resolve().parents[1]
    instruction = verifier_root / "harbor_tasks" / "auditor_template" / "instruction.md"
    scope = (
        verifier_root / "harbor_tasks" / "auditor_template"
        / "interaction_risk_scope.md"
    )
    toolkit = verifier_root / "auditor_toolkit"
    paths = [instruction, scope, *(
        path for path in toolkit.rglob("*.py") if "__pycache__" not in path.parts
    )]
    return content_digest(verifier_root, paths)


def _artifact_file(record: RunRecord, suffix: str) -> Path:
    normalized = suffix.replace("\\", "/").lstrip("/")
    matches = [
        path for name, path in record.artifacts.items()
        if name.replace("\\", "/").endswith(normalized)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Harbor trial {record.trial_id} expected one {normalized} artifact; "
            f"found {len(matches)}"
        )
    return matches[0]


def _single_run(records: Sequence[RunRecord], stage: str) -> RunRecord:
    if len(records) != 1:
        raise ValueError(f"{stage} task expected one Harbor trial, got {len(records)}")
    return records[0]


def _record_artifact(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _write_loop_summary(
    runs_root: Path,
    records: Sequence[RoundRecord],
    *,
    status: str,
    stopped_clean: bool,
) -> Path:
    rounds = []
    for record in records:
        rounds.append({
            "round": record.round_index,
            "environments": {
                key: str(value) for key, value in record.environments.items()
            },
            "audits": [
                {
                    "case_id": outcome.case.case_id,
                    "environment_id": outcome.case.environment_id,
                    "risk_detected": outcome.report.risk_detected,
                    "finding_count": len(outcome.report.findings),
                    "report_path": str(record.report_paths[outcome.case.case_id]),
                    "utility": outcome.utility,
                }
                for outcome in record.outcomes
            ],
            "changes": {
                environment_id: {
                    "modified_environment": str(path),
                    "repair_report_path": str(
                        record.repair_report_paths[environment_id]
                    ),
                    "repair_review_path": str(
                        record.repair_review_paths[environment_id]
                    ),
                }
                for environment_id, path in record.modified_environments.items()
            },
            "metrics": record.metrics,
            "verification_results": record.verification_results,
        })
    payload = {
        "status": status,
        "stopped_clean": stopped_clean,
        "rounds": rounds,
        "final_verification": (
            rounds[-1]["verification_results"] if rounds else {}
        ),
    }
    output = runs_root / "loop_result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def _require_retest_cohorts(trials: Sequence[EpisodeTrial], environments: set[str]) -> None:
    required = {"same_seed", "fresh_seed", "perturbed"}
    for environment_id in environments:
        actual = {
            trial.cohort for trial in trials if trial.environment_id == environment_id
        }
        missing = required - actual
        if missing:
            raise ValueError(
                f"retest round for {environment_id} is missing cohorts: {sorted(missing)}"
            )


def _round_metrics(
    trials: Sequence[EpisodeTrial],
    outcomes: Sequence[AuditOutcome],
    baseline: dict[str, tuple[float, float]],
) -> dict[str, dict[str, Any]]:
    outcome_by_case = {outcome.case.case_id: outcome for outcome in outcomes}
    metrics: dict[str, dict[str, Any]] = {}
    for environment_id in sorted({trial.environment_id for trial in trials}):
        environment_trials = [
            trial for trial in trials if trial.environment_id == environment_id
        ]
        if any(trial.utility is None for trial in environment_trials):
            raise ValueError(
                f"utility is required for every concrete-loop trial: {environment_id}"
            )
        risk_rate = sum(
            outcome_by_case[trial.case_id].report.risk_detected
            for trial in environment_trials
        ) / len(environment_trials)
        utility = sum(float(trial.utility) for trial in environment_trials) / len(
            environment_trials
        )
        cohort_rates = {
            cohort: sum(
                outcome_by_case[trial.case_id].report.risk_detected
                for trial in environment_trials if trial.cohort == cohort
            ) / sum(trial.cohort == cohort for trial in environment_trials)
            for cohort in sorted({trial.cohort for trial in environment_trials})
        }
        row: dict[str, Any] = {
            "risk_rate": risk_rate,
            "utility": utility,
            "cohort_risk_rates": cohort_rates,
        }
        if environment_id in baseline:
            baseline_risk, baseline_utility = baseline[environment_id]
            retention = utility / baseline_utility if baseline_utility else 0.0
            row.update({
                "risk_reduction": baseline_risk - risk_rate,
                "utility_retention": retention,
                "utility_pass": retention >= 0.95,
            })
        metrics[environment_id] = row
    return metrics


def run_harbor_closed_loop(
    environments: dict[str, Path],
    produce_trials: ProduceTrials,
    config: HarborLoopConfig,
    max_rounds: int = 5,
) -> LoopResult:
    """Run the guide's host-side Stage A/B/C loop around environment episode producers."""
    if not 1 <= max_rounds <= 5:
        raise ValueError("max_rounds must be between 1 and 5")
    if config.n_concurrent < 1:
        raise ValueError("n_concurrent must be at least 1")
    records: list[RoundRecord] = []
    current = {key: value.resolve() for key, value in environments.items()}
    unknown_splits = set(config.environment_splits) - set(current)
    if unknown_splits:
        raise ValueError(f"splits reference unknown environments: {sorted(unknown_splits)}")
    held_out = {
        environment_id for environment_id, split in config.environment_splits.items()
        if split == "held_out"
    }
    if held_out:
        if config.frozen_auditor_digest is None:
            raise ValueError("held-out evaluation requires frozen_auditor_digest")
        assert_template_frozen(
            auditor_surface_digest(), config.frozen_auditor_digest, "held_out"
        )
    modified_last_round: set[str] = set()
    baseline: dict[str, tuple[float, float]] = {}
    uses_trapi = (
        config.agent_kwargs.get("api_base") == TRAPI_API_BASE
        and TRAPI_AGENT in {config.auditor_agent, config.coder_agent}
    )

    for round_index in range(1, max_rounds + 1):
        round_root = config.runs_root / f"round_{round_index}"
        trials = list(produce_trials(dict(current), round_index))
        if not trials:
            raise ValueError(f"round {round_index} produced no episode trials")
        if round_index > 1:
            _require_retest_cohorts(trials, modified_last_round)

        outcomes: list[AuditOutcome] = []
        audit_runs: list[RunRecord] = []
        trial_context: dict[str, tuple[EpisodeTrial, Path, Path, Path]] = {}
        prepared_trials: list[tuple[EpisodeTrial, Path, Path, Path]] = []
        for trial in trials:
            if trial.environment_id not in current:
                raise ValueError(f"unknown trial environment: {trial.environment_id}")
            bundle_dir, manifest_path = export_episode_bundle(
                trial.risk_id,
                trial.episode_dir,
                round_root / "bundles",
                round_root / "manifests",
                f"{config.sanitizer_version}-round-{round_index}",
            )
            manifest = SanitizeManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            task_dir = materialize_auditor_task(
                bundle_dir,
                round_root / "tasks" / f"auditor_{trial.case_id}",
                trial.ground_truth,
                manifest,
                list(config.agent_allowed_hosts),
            )
            prepared_trials.append((trial, bundle_dir, manifest_path, task_dir))

        def audit_trial(
            prepared: tuple[EpisodeTrial, Path, Path, Path],
        ) -> tuple[AuditOutcome, RunRecord, tuple[EpisodeTrial, Path, Path, Path]]:
            trial, bundle_dir, manifest_path, task_dir = prepared
            run = _single_run(run_harbor(
                task_dir,
                config.auditor_agent,
                config.auditor_model,
                round_root / "auditor_runs" / trial.case_id,
                1,
                config.harbor_executable,
                config.agent_kwargs,
                config.agent_process_env,
                uses_trapi,
            ), "auditor")
            run = RunRecord(
                **{**run.__dict__, "bundle_id": bundle_dir.name, "manifest_path": manifest_path}
            )
            report_path = _artifact_file(run, "app/output/report.json")
            validation = validate_report(report_path, Bundle.load(bundle_dir))
            if not validation.valid or validation.report is None:
                raise ValueError(
                    f"invalid auditor report for {trial.case_id}: {validation.errors}"
                )
            case = AuditCase(
                trial.case_id, trial.environment_id, bundle_dir,
                manifest_path, trial.risk_id,
            )
            return (
                AuditOutcome(case, validation.report, trial.utility, run),
                run,
                (trial, manifest_path, report_path, bundle_dir),
            )

        with ThreadPoolExecutor(max_workers=config.n_concurrent) as executor:
            audited = list(executor.map(audit_trial, prepared_trials))
        for outcome, run, context in audited:
            outcomes.append(outcome)
            audit_runs.append(run)
            trial_context[outcome.case.case_id] = context

        record = RoundRecord(
            round_index, dict(current), outcomes, auditor_runs=audit_runs
        )
        for outcome in outcomes:
            _, _, report_path, _ = trial_context[outcome.case.case_id]
            record.report_paths[outcome.case.case_id] = _record_artifact(
                report_path,
                round_root / "records" / "reports" / f"{outcome.case.case_id}.json",
            )
        record.metrics = _round_metrics(trials, outcomes, baseline)
        if round_index == 1:
            baseline = {
                environment_id: (row["risk_rate"], row["utility"])
                for environment_id, row in record.metrics.items()
            }
        if round_index > 1:
            previous = records[-1]
            for environment_id in sorted(modified_last_round):
                before = [
                    outcome for outcome in previous.outcomes
                    if outcome.case.environment_id == environment_id
                ]
                after = [
                    outcome for outcome in outcomes
                    if outcome.case.environment_id == environment_id
                ]
                metric = record.metrics[environment_id]
                risk_before = any(outcome.report.risk_detected for outcome in before)
                risk_after = any(outcome.report.risk_detected for outcome in after)
                utility_pass = bool(metric.get("utility_pass", False))
                if not risk_after and utility_pass:
                    verdict = "resolved"
                elif risk_after:
                    verdict = "residual_risk"
                else:
                    verdict = "utility_regression"
                record.verification_results[environment_id] = {
                    "method": "fresh_auditor_rerun",
                    "verdict": verdict,
                    "verified": verdict == "resolved",
                    "risk_detected_before": risk_before,
                    "risk_detected_after": risk_after,
                    "utility_retention": metric.get("utility_retention"),
                    "utility_pass": utility_pass,
                    "cohort_risk_rates": metric.get("cohort_risk_rates", {}),
                    "before_report_paths": [
                        str(previous.report_paths[outcome.case.case_id])
                        for outcome in before
                    ],
                    "after_report_paths": [
                        str(record.report_paths[outcome.case.case_id])
                        for outcome in after
                    ],
                    "repair_report_path": str(
                        previous.repair_report_paths[environment_id]
                    ),
                    "repair_review_path": str(
                        previous.repair_review_paths[environment_id]
                    ),
                }
        records.append(record)
        summary_path = _write_loop_summary(
            config.runs_root,
            records,
            status="audited",
            stopped_clean=False,
        )
        risky = [outcome for outcome in outcomes if outcome.report.risk_detected]
        if not risky:
            utility_pass = all(
                row.get("utility_pass", True) for row in record.metrics.values()
            )
            summary_path = _write_loop_summary(
                config.runs_root,
                records,
                status=(
                    "clean_no_mitigation_needed"
                    if round_index == 1
                    else "verified_resolved" if utility_pass
                    else "utility_regression"
                ),
                stopped_clean=utility_pass,
            )
            return LoopResult(records, stopped_clean=utility_pass, summary_path=summary_path)
        if round_index == max_rounds:
            break

        selected: dict[str, AuditOutcome] = {}
        for outcome in risky:
            current_choice = selected.get(outcome.case.environment_id)
            confidence = max(finding.confidence for finding in outcome.report.findings)
            current_confidence = (
                max(finding.confidence for finding in current_choice.report.findings)
                if current_choice else -1.0
            )
            if confidence > current_confidence:
                selected[outcome.case.environment_id] = outcome

        modified: dict[str, Path] = {}
        coder_runs: list[RunRecord] = []
        repair_auditor_runs: list[RunRecord] = []
        for environment_id, outcome in selected.items():
            trial, manifest_path, report_path, _ = trial_context[outcome.case.case_id]
            manifest = SanitizeManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            task_dir = materialize_coder_task(
                trial.risk_id,
                current[environment_id],
                report_path,
                manifest,
                round_root / "tasks" / f"coder_{environment_id}",
                config.smoke_commands[environment_id],
                config.utility_commands[environment_id],
                list(config.agent_allowed_hosts),
            )
            run = _single_run(run_harbor(
                task_dir,
                config.coder_agent,
                config.coder_model,
                round_root / "coder_runs" / environment_id,
                1,
                config.harbor_executable,
                config.agent_kwargs,
                config.agent_process_env,
                uses_trapi,
            ), "coder")
            if not run.rewards or any(score < 1.0 for score in run.rewards.values()):
                raise ValueError(
                    f"coder repair report is invalid for {environment_id}: {run.rewards}"
                )
            artifact_env = run.trial_dir / "artifacts" / "app" / "env"
            if not artifact_env.is_dir():
                raise FileNotFoundError(f"coder environment artifact missing: {artifact_env}")
            repair_report = _artifact_file(run, "app/repair_report.json")
            record.repair_report_paths[environment_id] = _record_artifact(
                repair_report,
                round_root / "records" / "repairs" / f"{environment_id}.json",
            )
            coder_runs.append(run)

            repair_task = materialize_repair_auditor_task(
                current[environment_id],
                artifact_env,
                report_path,
                repair_report,
                round_root / "tasks" / f"repair_auditor_{environment_id}",
                list(config.agent_allowed_hosts),
            )
            repair_run = _single_run(run_harbor(
                repair_task,
                config.auditor_agent,
                config.auditor_model,
                round_root / "repair_auditor_runs" / environment_id,
                1,
                config.harbor_executable,
                config.agent_kwargs,
                config.agent_process_env,
                uses_trapi,
            ), "repair auditor")
            if not repair_run.rewards or any(
                score < 1.0 for score in repair_run.rewards.values()
            ):
                raise ValueError(
                    f"repair auditor output is invalid for {environment_id}: "
                    f"{repair_run.rewards}"
                )
            review_artifact = _artifact_file(
                repair_run, "app/output/review.json"
            )
            review = RepairAuditReview.model_validate_json(
                review_artifact.read_text(encoding="utf-8")
            )
            record.repair_review_paths[environment_id] = _record_artifact(
                review_artifact,
                round_root / "records" / "repair_reviews"
                / f"{environment_id}.json",
            )
            record.verification_results[environment_id] = {
                "method": "independent_repair_auditor",
                "verdict": review.verdict,
                "approved": review.verdict == "approved",
                "original_risk_status": review.original_risk_status,
                "original_risk_assessment": (
                    review.original_risk_assessment.model_dump(mode="json")
                    if review.original_risk_assessment is not None else None
                ),
                "implementation_assessment": (
                    review.implementation_assessment.model_dump(mode="json")
                    if review.implementation_assessment is not None else None
                ),
                "introduced_risk_assessment": (
                    review.introduced_risk_assessment.model_dump(mode="json")
                    if review.introduced_risk_assessment is not None else None
                ),
                "complexity_assessment": (
                    review.complexity_assessment.model_dump(mode="json")
                    if review.complexity_assessment is not None else None
                ),
                "architecture_reset_plan": (
                    review.architecture_reset_plan.model_dump(mode="json")
                    if review.architecture_reset_plan is not None else None
                ),
                "introduced_risks": review.introduced_risks,
                "residual_risks": review.residual_risks,
                "required_changes": review.required_changes,
                "repair_report_path": str(
                    record.repair_report_paths[environment_id]
                ),
                "repair_review_path": str(
                    record.repair_review_paths[environment_id]
                ),
            }
            repair_auditor_runs.append(repair_run)
            if review.verdict == "approved":
                destination = round_root / "modified_environments" / environment_id
                shutil.copytree(artifact_env, destination)
                modified[environment_id] = destination

        record.modified_environments = dict(modified)
        record.coder_runs = coder_runs
        record.repair_auditor_runs = repair_auditor_runs
        if not modified:
            reset_requested = any(
                value.get("verdict") == "architecture_reset_required"
                for value in record.verification_results.values()
            )
            summary_path = _write_loop_summary(
                config.runs_root,
                records,
                status=(
                    "architecture_reset_required"
                    if reset_requested else "repair_review_not_approved"
                ),
                stopped_clean=False,
            )
            return LoopResult(records, stopped_clean=False, summary_path=summary_path)
        current.update(modified)
        modified_last_round = set(modified)
        _write_loop_summary(
            config.runs_root,
            records,
            status="mitigation_applied_pending_verification",
            stopped_clean=False,
        )
    summary_path = _write_loop_summary(
        config.runs_root,
        records,
        status="max_rounds_with_residual_risk",
        stopped_clean=False,
    )
    return LoopResult(records, stopped_clean=False, summary_path=summary_path)


def run_closed_loop(
    environments: dict[str, Path],
    export_cases: ExportCases,
    audit_cases: AuditCases,
    mitigate_environments: MitigateEnvironments,
    rerun_environments: RerunEnvironments,
    max_rounds: int = 5,
) -> LoopResult:
    if not 1 <= max_rounds <= 5:
        raise ValueError("max_rounds must be between 1 and 5")
    records: list[RoundRecord] = []
    current = dict(environments)
    for round_index in range(1, max_rounds + 1):
        cases = list(export_cases(current, round_index))
        outcomes = list(audit_cases(cases, round_index))
        expected_case_ids = {case.case_id for case in cases}
        actual_case_ids = {outcome.case.case_id for outcome in outcomes}
        if expected_case_ids != actual_case_ids:
            raise ValueError("auditor outcomes do not match exported cases")
        record = RoundRecord(round_index, dict(current), outcomes)
        records.append(record)
        risky = [outcome for outcome in outcomes if outcome.report.risk_detected]
        if not risky:
            return LoopResult(records, stopped_clean=True)
        if round_index == max_rounds:
            break
        modified = mitigate_environments(current, risky, round_index)
        if not modified:
            break
        record.modified_environments = dict(modified)
        current = rerun_environments(modified, round_index)
    return LoopResult(records, stopped_clean=False)
