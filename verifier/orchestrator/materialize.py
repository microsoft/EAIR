"""Materialize disposable Harbor tasks without crossing trust boundaries."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from risk_environments import get_risk_environment
from verifier.orchestrator.pipeline import TRAPI_ALLOWED_HOSTS
from verifier.orchestrator.profiles import render_auditor_instruction, resolve_graph_profile
from verifier.schemas.repair import RepairAuditReview, RepairReport
from verifier.schemas.report import RiskReport
from verifier.schemas.sanitize_manifest import SanitizeManifest


COPY_IGNORE_PATTERNS = ("__pycache__", "*.pyc", "*.pyo", ".pytest_cache", "task", "output")
RESERVED_CUSTOM_ENVIRONMENT_ALIASES = frozenset({
    "a2", "b2", "tacitcollusion", "aggregatorsway",
    "a2tacitcollusion", "tacitcollusiona2", "b2aggregatorsway", "aggregatorswayb2",
})

APPROVED_MODEL_API_HOSTS = {
    "api.anthropic.com",
    "api.cohere.com",
    "api.mistral.ai",
    "api.openai.com",
    "api.x.ai",
    "generativelanguage.googleapis.com",
    "openrouter.ai",
    "trapi.research.microsoft.com",
}


def _copy_path(path: Path) -> Path:
    """Return an extended Windows path for deep generated artifact trees."""
    resolved = path.resolve()
    if os.name == "nt" and not str(resolved).startswith("\\\\?\\"):
        return Path("\\\\?\\" + str(resolved))
    return resolved


def _copy_session_memory(
    source: Path | None,
    destination: Path,
    iteration: int,
) -> None:
    if source is not None:
        if not source.is_dir():
            raise FileNotFoundError(f"session memory does not exist: {source}")
        shutil.copytree(_copy_path(source), _copy_path(destination))
    else:
        destination.mkdir(parents=True)
        (destination / "manifest.json").write_text(
            json.dumps({"iteration": iteration, "rounds": []}, indent=2) + "\n",
            encoding="utf-8",
        )
    if not (destination / "manifest.json").is_file():
        raise FileNotFoundError("session memory requires manifest.json")


def _is_approved_model_host(host: str) -> bool:
    return (
        host in APPROVED_MODEL_API_HOSTS
        or host.endswith(".openai.azure.com")
        or host.endswith(".services.ai.azure.com")
    )


def _set_agent_allowed_hosts(task_path: Path, allowed_hosts: list[str]) -> None:
    if not allowed_hosts:
        raise ValueError("at least one model API host must be allowed")
    if any("://" in host or "/" in host for host in allowed_hosts):
        raise ValueError("allowed hosts must be hostnames, not URLs or paths")
    unapproved = sorted(host for host in allowed_hosts if not _is_approved_model_host(host))
    if unapproved:
        raise ValueError(f"unapproved model API hosts: {unapproved}")
    text = task_path.read_text(encoding="utf-8")
    rendered = ", ".join(json.dumps(host) for host in allowed_hosts)
    updated, replacements = re.subn(
        r"(?m)^allowed_hosts\s*=\s*\[[^\r\n]*\]$",
        f"allowed_hosts = [{rendered}]",
        text,
        count=1,
    )
    if replacements != 1:
        raise ValueError(f"task template has no agent allowed_hosts entry: {task_path}")
    task_path.write_text(updated, encoding="utf-8")


def _set_graph_profile(dockerfile: Path, profile: str) -> None:
    text = dockerfile.read_text(encoding="utf-8")
    anchor = "ENV PYTHONPATH="
    if text.count(anchor) != 1:
        raise ValueError(f"task template must contain one PYTHONPATH entry: {dockerfile}")
    dockerfile.write_text(
        text.replace(anchor, f"ENV VERIFIER_GRAPH_PROFILE={profile}\n{anchor}", 1),
        encoding="utf-8",
    )


def _deanonymize_report(
    report_path: Path,
    manifest: SanitizeManifest,
) -> RiskReport:
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    inverse: dict[str, str] = {}
    for mapping in (
        manifest.env_ids,
        manifest.agent_ids,
        manifest.tool_ids,
        manifest.document_ids,
        manifest.policy_ids,
        manifest.episode_ids,
    ):
        inverse.update({anonymized: real for real, anonymized in mapping.items()})

    def restore(value):
        if isinstance(value, str):
            result = value
            for anonymized in sorted(inverse, key=lambda item: (-len(item), item)):
                pattern = rf"(?<![A-Za-z0-9_]){re.escape(anonymized)}(?![A-Za-z0-9_])"
                result = re.sub(pattern, inverse[anonymized], result)
            return result
        if isinstance(value, list):
            return [restore(item) for item in value]
        if isinstance(value, dict):
            return {restore(str(key)): restore(item) for key, item in value.items()}
        return value

    report = RiskReport.model_validate(restore(raw))
    if not report.findings:
        raise ValueError("coder tasks require an auditor report with findings")
    return report


def _copy_bundle(source: Path, destination: Path) -> None:
    source_root = source.resolve()
    ignore_cache = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache")

    def ignore_files(directory: str, names: list[str]) -> set[str]:
        ignored = set(ignore_cache(directory, names))
        if Path(directory).resolve() == source_root:
            ignored.update({"ground_truth.json", "manifest.json", "task", "output"} & set(names))
        return ignored

    shutil.copytree(source, destination, ignore=ignore_files)


def _copy_runtime(destination: Path, include_grader: bool = False) -> None:
    source_root = Path(__file__).resolve().parents[1]
    package_root = destination / "verifier"
    ignore = shutil.ignore_patterns(*COPY_IGNORE_PATTERNS)
    shutil.copytree(source_root / "schemas", package_root / "schemas", ignore=ignore)
    shutil.copytree(
        source_root / "auditor_toolkit", package_root / "auditor_toolkit", ignore=ignore
    )
    (package_root / "orchestrator").mkdir()
    shutil.copy2(
        source_root / "orchestrator" / "profiles.py",
        package_root / "orchestrator" / "profiles.py",
    )
    (package_root / "orchestrator" / "__init__.py").write_text(
        '"""Isolated auditor profile configuration."""\n', encoding="utf-8"
    )
    if include_grader:
        (package_root / "eval").mkdir(parents=True)
        shutil.copy2(source_root / "eval" / "matching.py", package_root / "eval" / "matching.py")
        (package_root / "eval" / "__init__.py").write_text(
            '"""Separate-verifier matching runtime."""\n', encoding="utf-8"
        )
    (package_root / "__init__.py").write_text(
        '"""Minimal verifier runtime copied into a Harbor image."""\n',
        encoding="utf-8",
    )


def materialize_auditor_task(
    bundle_dir: Path,
    output_dir: Path,
    ground_truth: dict | None,
    manifest: SanitizeManifest,
    agent_allowed_hosts: list[str] | None = None,
    *,
    profile: str = "v3-annotated",
    scope_text: str | None = None,
) -> Path:
    """Return the task directory; None truth requests discovery-only validation.

    Truth (including the explicit null marker) and the manifest remain in tests.
    The API defaults to annotated graphs regardless of VERIFIER_GRAPH_PROFILE.
    Topology uses api.openai.com unless agent_allowed_hosts is supplied.
    """
    profile = resolve_graph_profile(profile)
    if ground_truth is not None and not isinstance(ground_truth, dict):
        raise TypeError("ground_truth must be a dictionary or None")
    if scope_text is not None and not scope_text.strip():
        raise ValueError("scope_text must be nonempty when supplied")
    if output_dir.exists():
        raise FileExistsError(f"task directory already exists: {output_dir}")
    template = Path(__file__).resolve().parents[1] / "harbor_tasks" / "auditor_template"
    shutil.copytree(template, output_dir, ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS))
    default_hosts = (
        ["api.openai.com"] if profile == "v3-topology" else list(TRAPI_ALLOWED_HOSTS)
    )
    _set_agent_allowed_hosts(
        output_dir / "task.toml",
        agent_allowed_hosts if agent_allowed_hosts is not None else default_hosts,
    )
    _copy_bundle(bundle_dir, output_dir / "environment" / "bundle")
    _copy_bundle(bundle_dir, output_dir / "tests" / "bundle")
    _copy_runtime(output_dir / "environment" / "verifier_pkg")
    _copy_runtime(output_dir / "tests" / "verifier_pkg", include_grader=True)
    for directory in ("environment", "tests"):
        _set_graph_profile(output_dir / directory / "Dockerfile", profile)

    instruction_path = output_dir / "instruction.md"
    instruction = render_auditor_instruction(
        instruction_path.read_text(encoding="utf-8"), profile
    )
    scope_path = output_dir / "interaction_risk_scope.md"
    scope_instruction = (
        scope_path.read_text(encoding="utf-8") if scope_text is None else scope_text
    ).strip()
    if scope_text is not None:
        scope_path.write_text(scope_instruction + "\n", encoding="utf-8")
    instruction_path.write_text(
        instruction.replace(
            "{{INTERACTION_RISK_SCOPE}}", scope_instruction
        ),
        encoding="utf-8",
    )

    (output_dir / "tests" / "ground_truth.json").write_text(
        json.dumps(ground_truth, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "tests" / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return output_dir


def materialize_coder_task(
    risk_id: str,
    environment_source: Path,
    report_path: Path,
    manifest: SanitizeManifest,
    output_dir: Path,
    smoke_command: list[str] | None = None,
    utility_command: list[str] | None = None,
    agent_allowed_hosts: list[str] | None = None,
    feedback_path: Path | None = None,
    session_memory: Path | None = None,
    iteration: int = 1,
    retry_note: str | None = None,
    *,
    custom_environment: bool = False,
) -> Path:
    """Return a coder task for a registered or explicitly opted-in custom world.

    Custom IDs must be alphanumeric slugs joined with hyphens or underscores,
    must exactly match a manifest.env_ids key, and cannot alias A2 or B2.
    Smoke and utility commands remain mandatory in both modes.
    Custom tasks use api.openai.com unless agent_allowed_hosts is supplied.
    """
    if not isinstance(custom_environment, bool):
        raise TypeError("custom_environment must be a bool")
    if custom_environment:
        if not isinstance(risk_id, str) or re.fullmatch(
            r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", risk_id
        ) is None:
            raise ValueError("custom risk_id must be a nonempty alphanumeric slug")
        normalized = risk_id.casefold().replace("-", "").replace("_", "")
        if normalized in RESERVED_CUSTOM_ENVIRONMENT_ALIASES:
            raise ValueError("reserved A2/B2 environment aliases are not supported")
        if risk_id not in manifest.env_ids:
            raise ValueError("custom risk_id must exactly match a key in manifest.env_ids")
    else:
        get_risk_environment(risk_id)
    if output_dir.exists():
        raise FileExistsError(f"task directory already exists: {output_dir}")
    if not environment_source.is_dir():
        raise FileNotFoundError(f"environment source does not exist: {environment_source}")
    if not smoke_command or not utility_command:
        raise ValueError("coder tasks require both smoke_command and utility_command")
    if iteration < 1:
        raise ValueError("iteration must be at least 1")
    report = _deanonymize_report(report_path, manifest)
    template = Path(__file__).resolve().parents[1] / "harbor_tasks" / "coder_template"
    ignore = shutil.ignore_patterns(*COPY_IGNORE_PATTERNS)
    shutil.copytree(template, output_dir, ignore=ignore)
    default_hosts = (
        ["api.openai.com"] if custom_environment else list(TRAPI_ALLOWED_HOSTS)
    )
    _set_agent_allowed_hosts(
        output_dir / "task.toml",
        agent_allowed_hosts if agent_allowed_hosts is not None else default_hosts,
    )
    shutil.copytree(
        _copy_path(environment_source),
        _copy_path(output_dir / "environment" / "env"),
        ignore=ignore,
    )
    rendered_report = report.model_dump_json(indent=2) + "\n"
    (output_dir / "environment" / "report.json").write_text(
        rendered_report, encoding="utf-8"
    )
    (output_dir / "tests" / "report.json").write_text(
        rendered_report, encoding="utf-8"
    )
    shutil.copy2(
        output_dir / "operator_library.md",
        output_dir / "environment" / "operator_library.md",
    )

    schema_root = output_dir / "tests" / "schema_pkg" / "verifier"
    source_root = Path(__file__).resolve().parents[1]
    shutil.copytree(source_root / "schemas", schema_root / "schemas", ignore=ignore)
    (schema_root / "__init__.py").write_text(
        '"""Minimal repair-report schema runtime."""\n', encoding="utf-8"
    )
    context = {
        "risk_id": risk_id,
        "smoke_command": smoke_command,
        "utility_command": utility_command,
        "timeout_sec": 900,
    }
    (output_dir / "environment" / "validation_commands.json").write_text(
        json.dumps(context, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    feedback: dict = {}
    if feedback_path is not None:
        feedback = RepairAuditReview.model_validate_json(
            feedback_path.read_text(encoding="utf-8")
        ).model_dump(mode="json")
    (output_dir / "environment" / "feedback.json").write_text(
        json.dumps(feedback, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "tests" / "feedback.json").write_text(
        json.dumps(feedback, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "environment" / "retry_note.txt").write_text(
        (retry_note or "").strip() + ("\n" if retry_note else ""),
        encoding="utf-8",
    )
    _copy_session_memory(
        session_memory,
        output_dir / "environment" / "session_memory",
        iteration,
    )
    return output_dir


def materialize_repair_auditor_task(
    pristine_environment: Path,
    modified_environment: Path,
    report_path: Path,
    repair_report_path: Path,
    output_dir: Path,
    agent_allowed_hosts: list[str] | None = None,
    session_memory: Path | None = None,
    iteration: int = 1,
    latest_feedback_path: Path | None = None,
    retry_note: str | None = None,
) -> Path:
    """Create an independent semantic review task for a coder repair."""
    if output_dir.exists():
        raise FileExistsError(f"task directory already exists: {output_dir}")
    if not pristine_environment.is_dir():
        raise FileNotFoundError(
            f"pristine environment does not exist: {pristine_environment}"
        )
    if not modified_environment.is_dir():
        raise FileNotFoundError(
            f"modified environment does not exist: {modified_environment}"
        )
    if iteration < 1:
        raise ValueError("iteration must be at least 1")
    report = RiskReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    repair = RepairReport.model_validate_json(
        repair_report_path.read_text(encoding="utf-8")
    )
    expected = {
        (finding_index, item.plan_item_id)
        for finding_index, finding in enumerate(report.findings)
        for item in finding.mitigation_plan
    }
    actual = {
        (item.finding_index, item.plan_item_id) for item in repair.plan_items
    }
    if expected != actual:
        raise ValueError(
            f"repair report plan coverage mismatch: "
            f"expected={sorted(expected)} actual={sorted(actual)}"
        )

    template = (
        Path(__file__).resolve().parents[1]
        / "harbor_tasks"
        / "repair_auditor_template"
    )
    shutil.copytree(template, output_dir)
    _set_agent_allowed_hosts(
        output_dir / "task.toml",
        agent_allowed_hosts or list(TRAPI_ALLOWED_HOSTS),
    )
    environment = output_dir / "environment"
    shutil.copytree(
        _copy_path(pristine_environment), _copy_path(environment / "pristine")
    )
    shutil.copytree(
        _copy_path(modified_environment), _copy_path(environment / "modified")
    )
    shutil.copy2(report_path, environment / "original_report.json")
    shutil.copy2(repair_report_path, environment / "repair_report.json")
    shutil.copy2(
        Path(__file__).resolve().parents[1]
        / "harbor_tasks"
        / "coder_template"
        / "operator_library.md",
        environment / "operator_library.md",
    )
    latest_feedback = None
    if latest_feedback_path is not None:
        latest_feedback = RepairAuditReview.model_validate_json(
            latest_feedback_path.read_text(encoding="utf-8")
        ).model_dump(mode="json")
    (environment / "review_context.json").write_text(
        json.dumps(
            {
                "iteration": iteration,
                "latest_feedback": latest_feedback,
                "retry_note": retry_note,
            },
            ensure_ascii=True,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    _copy_session_memory(
        session_memory,
        environment / "session_memory",
        iteration,
    )

    tests = output_dir / "tests"
    shutil.copy2(report_path, tests / "original_report.json")
    schema_root = tests / "schema_pkg" / "verifier"
    source_root = Path(__file__).resolve().parents[1]
    shutil.copytree(source_root / "schemas", schema_root / "schemas")
    (schema_root / "__init__.py").write_text(
        '"""Minimal repair-audit schema runtime."""\n', encoding="utf-8"
    )
    return output_dir
