"""Trusted Harbor subprocess runner and artifact collection."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


TRAPI_AGENT = "terminus-2"
TRAPI_MODEL = "openai/gpt-5.6-sol_2026-07-09"
TRAPI_API_BASE = "https://trapi.research.microsoft.com/redmond/interactive/openai/v1"
TRAPI_ALLOWED_HOSTS = ("trapi.research.microsoft.com",)
TRAPI_SCOPE = "api://trapi/.default"
TRAPI_AGENT_KWARGS = {
    "api_base": TRAPI_API_BASE,
    "reasoning_effort": "high",
}


def parse_agent_kwargs(values: list[str] | None) -> dict[str, str]:
    """Parse repeatable Harbor KEY=VALUE agent kwargs."""
    parsed: dict[str, str] = {}
    for value in values or []:
        key, separator, item = value.partition("=")
        if not separator or not key:
            raise ValueError(f"agent kwarg must use KEY=VALUE: {value}")
        parsed[key] = item
    return parsed


class HarborUnavailableError(RuntimeError):
    pass


class HarborRunError(RuntimeError):
    pass


def get_trapi_bearer_token(scope: str = TRAPI_SCOPE) -> str:
    """Acquire a host-only TRAPI token from the existing Azure identity."""
    from azure.identity import (
        AzureCliCredential,
        ChainedTokenCredential,
        ManagedIdentityCredential,
    )

    credential = ChainedTokenCredential(
        AzureCliCredential(),
        ManagedIdentityCredential(),
    )
    return credential.get_token(scope).token


@dataclass(frozen=True)
class RunRecord:
    job_id: str
    trial_id: str
    task_name: str | None
    trial_dir: Path
    result_path: Path
    reward_path: Path | None
    artifacts: dict[str, Path]
    rewards: dict[str, float]
    bundle_id: str | None = None
    manifest_path: Path | None = None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _find_reward(trial_dir: Path) -> tuple[Path | None, dict[str, float]]:
    candidates = [
        trial_dir / "verifier" / "reward.json",
        trial_dir / "verifier" / "reward.txt",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        if path.suffix == ".json":
            value = _read_json(path)
            return path, {
                key: float(item)
                for key, item in value.items()
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            }
        try:
            return path, {"reward": float(path.read_text(encoding="utf-8").strip())}
        except ValueError:
            return path, {}
    return None, {}


def collect_job_records(job_dir: Path) -> list[RunRecord]:
    records: list[RunRecord] = []
    for trial_dir in sorted(path for path in job_dir.iterdir() if path.is_dir()):
        result_path = trial_dir / "result.json"
        config = _read_json(trial_dir / "config.json")
        if not result_path.is_file():
            continue
        artifacts_root = trial_dir / "artifacts"
        artifacts = {
            path.relative_to(artifacts_root).as_posix(): path
            for path in artifacts_root.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        } if artifacts_root.is_dir() else {}
        reward_path, rewards = _find_reward(trial_dir)
        task = config.get("task", {})
        task_name = task.get("name") if isinstance(task, dict) else config.get("task_name")
        records.append(RunRecord(
            job_id=job_dir.name,
            trial_id=trial_dir.name,
            task_name=task_name,
            trial_dir=trial_dir,
            result_path=result_path,
            reward_path=reward_path,
            artifacts=artifacts,
            rewards=rewards,
        ))
    return records


def _harbor_command_prefix(
    harbor_executable: str,
    resolved_executable: str,
) -> list[str]:
    if harbor_executable == "harbor" and sys.platform == "win32":
        app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        tool_python = app_data / "uv" / "tools" / "harbor" / "Scripts" / "python.exe"
        if tool_python.is_file():
            return [
                str(tool_python),
                "-c",
                "from harbor.cli.main import app; app()",
            ]
    return [resolved_executable]


def run_harbor(
    task_or_dataset: Path,
    agent: str,
    model: str,
    runs_dir: Path,
    n_concurrent: int = 1,
    harbor_executable: str = "harbor",
    agent_kwargs: Mapping[str, str] | None = None,
    process_env: Mapping[str, str] | None = None,
    trapi_auth: bool = False,
) -> list[RunRecord]:
    executable = shutil.which(harbor_executable)
    if executable is None and harbor_executable == "harbor":
        candidates = [
            Path.home() / ".local" / "bin" / "harbor.exe",
            Path.home() / ".local" / "bin" / "harbor",
        ]
        executable = next((str(path) for path in candidates if path.is_file()), None)
    if executable is None:
        raise HarborUnavailableError(
            "Harbor CLI is not installed. Install with: uv tool install harbor"
        )
    runs_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = runs_dir / "jobs"
    before = set(jobs_dir.iterdir()) if jobs_dir.is_dir() else set()
    command = [
        *_harbor_command_prefix(harbor_executable, executable),
        "run",
        "-p", str(task_or_dataset.resolve()),
        "-a", agent,
        "-m", model,
        "-n", str(n_concurrent),
        "--yes",
    ]
    for key, value in (agent_kwargs or {}).items():
        command.extend(["--agent-kwarg", f"{key}={value}"])
    environment = os.environ.copy()
    environment.update(process_env or {})
    if trapi_auth:
        environment["OPENAI_API_KEY"] = get_trapi_bearer_token()
    completed = subprocess.run(
        command,
        cwd=runs_dir,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise HarborRunError(
            f"Harbor exited {completed.returncode}: {(completed.stderr or completed.stdout)[-4000:]}"
        )
    after = set(jobs_dir.iterdir()) if jobs_dir.is_dir() else set()
    created = sorted(after - before, key=lambda path: path.stat().st_mtime)
    if not created:
        raise HarborRunError("Harbor completed but no new job directory was found")
    records: list[RunRecord] = []
    for job_dir in created:
        records.extend(collect_job_records(job_dir))
    return records
