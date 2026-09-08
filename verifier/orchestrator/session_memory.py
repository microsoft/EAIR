"""Build explicit cross-trial memory for iterative Coder/Auditor roles."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Sequence

from verifier.schemas.repair import RepairAuditReview, RepairReport


def select_repair_environment(
    current_environment: Path,
    original_environment: Path,
    rounds: Sequence[dict[str, Any]],
    latest_feedback: RepairAuditReview,
) -> tuple[Path, bool, str | None]:
    """Select the next input tree, applying an LLM-requested architecture reset."""
    if latest_feedback.verdict != "architecture_reset_required":
        return current_environment, False, None
    reset = latest_feedback.architecture_reset_plan
    if reset is None:
        raise ValueError("architecture reset verdict is missing its plan")
    selected = original_environment
    if reset.stable_baseline == "last_approved_environment":
        approved_round = next(
            (
                round_record for round_record in reversed(rounds)
                if round_record.get("verdict") == "approved"
            ),
            None,
        )
        if approved_round is not None:
            selected = Path(approved_round["output_environment"])
    return selected, True, str(selected)


def _copy(source: Path, destination: Path, memory_root: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(f"session artifact is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_path = source.resolve()
    destination_path = destination.resolve()
    if os.name == "nt":
        source_path = Path("\\\\?\\" + str(source_path))
        destination_path = Path("\\\\?\\" + str(destination_path))
    shutil.copy2(source_path, destination_path)
    relative = destination.relative_to(memory_root).as_posix()
    return f"/app/session_memory/{relative}"


def materialize_session_memory(
    output_dir: Path,
    *,
    risk_id: str,
    next_iteration: int,
    original_report: Path,
    original_auditor_trajectory: Path,
    rounds: Sequence[dict[str, Any]],
    pending_coder: dict[str, Any] | None = None,
) -> Path:
    """Persist complete prior role trajectories and reports for the next trial."""
    if output_dir.exists():
        raise FileExistsError(f"session memory already exists: {output_dir}")
    if not 1 <= next_iteration <= 5:
        raise ValueError("next_iteration must be between one and five")
    output_dir.mkdir(parents=True)

    manifest: dict[str, Any] = {
        "risk_id": risk_id,
        "next_iteration": next_iteration,
        "native_session_resume": False,
        "continuity_method": (
            "Complete prior trajectories and artifacts are injected into each new "
            "Harbor trial for the same role and model."
        ),
        "initial": {},
        "rounds": [],
        "pending_coder": None,
        "cumulative_changed_files": [],
        "architecture_memory": {
            "stable_baseline": "original_environment",
            "preserve_safety_properties": [],
            "replaceable_implementations": [],
            "failed_approaches": [],
            "allowed_removals": [],
            "latest_architecture_action": "continue_incremental",
        },
    }
    initial = output_dir / "initial"
    manifest["initial"] = {
        "auditor_report": _copy(
            original_report, initial / "auditor_report.json", output_dir
        ),
        "auditor_trajectory": _copy(
            original_auditor_trajectory,
            initial / "auditor_trajectory.json",
            output_dir,
        ),
    }

    cumulative_files: set[str] = set()
    for expected_iteration, round_record in enumerate(rounds, start=1):
        if round_record.get("iteration") != expected_iteration:
            raise ValueError("session-memory rounds must be contiguous from one")
        round_dir = output_dir / f"round_{expected_iteration}"
        repair_path = Path(round_record["repair_report"])
        feedback_path = Path(round_record["feedback_report"])
        repair = RepairReport.model_validate_json(
            repair_path.read_text(encoding="utf-8")
        )
        feedback = RepairAuditReview.model_validate_json(
            feedback_path.read_text(encoding="utf-8")
        )
        architecture_memory = manifest["architecture_memory"]
        architecture_memory["preserve_safety_properties"] = sorted(set(
            architecture_memory["preserve_safety_properties"]
            + feedback.preserve_from_previous_rounds
            + feedback.security_invariants
        ))
        if feedback.architecture_reset_plan is not None:
            reset = feedback.architecture_reset_plan
            architecture_memory.update({
                "stable_baseline": reset.stable_baseline,
                "preserve_safety_properties": sorted(set(
                    architecture_memory["preserve_safety_properties"]
                    + reset.preserve_safety_properties
                )),
                "replaceable_implementations": sorted(set(
                    architecture_memory["replaceable_implementations"]
                    + reset.replaceable_implementations
                )),
                "failed_approaches": sorted(set(
                    architecture_memory["failed_approaches"]
                    + reset.failed_approaches
                )),
                "allowed_removals": sorted(set(
                    architecture_memory["allowed_removals"]
                    + reset.allowed_removals
                )),
                "latest_architecture_action": "reset_required",
            })
        cumulative_files.update(repair.files_changed)
        manifest["rounds"].append({
            "iteration": expected_iteration,
            "input_environment": str(round_record["input_environment"]),
            "output_environment": str(round_record["output_environment"]),
            "coder_trajectory": _copy(
                Path(round_record["coder_trajectory"]),
                round_dir / "coder_trajectory.json",
                output_dir,
            ),
            "repair_report": _copy(
                repair_path, round_dir / "repair_report.json", output_dir
            ),
            "auditor_trajectory": _copy(
                Path(round_record["auditor_trajectory"]),
                round_dir / "auditor_trajectory.json",
                output_dir,
            ),
            "feedback_report": _copy(
                feedback_path, round_dir / "feedback_report.json", output_dir
            ),
            "verdict": feedback.verdict,
            "required_changes": feedback.required_changes,
            "changed_files": repair.files_changed,
            "original_risk_status": (
                feedback.original_risk_assessment.status
                if feedback.original_risk_assessment is not None
                else feedback.original_risk_status
            ),
            "implementation_status": (
                feedback.implementation_assessment.status
                if feedback.implementation_assessment is not None
                else None
            ),
            "introduced_risk_status": (
                feedback.introduced_risk_assessment.status
                if feedback.introduced_risk_assessment is not None
                else None
            ),
            "general_failure_class": feedback.general_failure_class,
        })
    if pending_coder is not None:
        pending_iteration = int(pending_coder["iteration"])
        if pending_iteration != next_iteration:
            raise ValueError("pending Coder iteration must equal next_iteration")
        pending_dir = output_dir / f"round_{pending_iteration}" / "pending"
        pending_repair = RepairReport.model_validate_json(
            Path(pending_coder["repair_report"]).read_text(encoding="utf-8")
        )
        cumulative_files.update(pending_repair.files_changed)
        manifest["pending_coder"] = {
            "iteration": pending_iteration,
            "input_environment": str(pending_coder["input_environment"]),
            "output_environment": str(pending_coder["output_environment"]),
            "coder_trajectory": _copy(
                Path(pending_coder["coder_trajectory"]),
                pending_dir / "coder_trajectory.json",
                output_dir,
            ),
            "repair_report": _copy(
                Path(pending_coder["repair_report"]),
                pending_dir / "repair_report.json",
                output_dir,
            ),
            "changed_files": pending_repair.files_changed,
        }
    manifest["cumulative_changed_files"] = sorted(cumulative_files)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_dir
