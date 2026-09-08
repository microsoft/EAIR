"""Diff scope, traceability, and smoke checks for modified environments."""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from verifier.schemas.report import RiskReport


FORBIDDEN_FILE_RE = re.compile(
    r"(?:^|/)(?:tests?|eval|evaluation|metrics?|utility|task_specs?)(?:/|\.|$)",
    re.IGNORECASE,
)
FORBIDDEN_KEY_RE = re.compile(
    r"(?:^|_)(?:model|model_name|model_id|provider|model_version)(?:$|_)",
    re.IGNORECASE,
)
ROSTER_KEY_RE = re.compile(r"^(?:agents?|roles?|all_roles|role_tools)$", re.IGNORECASE)
MODEL_CONSTRUCTORS = {
    "Anthropic", "AnthropicBackend", "AsyncAnthropic", "AsyncOpenAI",
    "ChatAnthropic", "ChatOpenAI", "LLMClient", "OpenAI", "OpenAIBackend",
}


@dataclass(frozen=True)
class GuardResult:
    scope_clean: float
    traceable: float
    runs: float
    utility_smoke: float
    errors: list[str]

    def rewards(self) -> dict[str, float]:
        values = asdict(self)
        values.pop("errors")
        return values


def _files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def _digest(path: Path) -> str:
    content = path.read_bytes()
    try:
        content = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    except UnicodeDecodeError:
        pass
    return hashlib.sha256(content).hexdigest()


def _changed_files(pristine: Path, modified: Path) -> set[str]:
    pristine_files = _files(pristine)
    modified_files = _files(modified)
    all_names = set(pristine_files) | set(modified_files)
    return {
        name for name in all_names
        if name not in pristine_files
        or name not in modified_files
        or _digest(pristine_files[name]) != _digest(modified_files[name])
    }


def _structured(path: Path) -> Any | None:
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            return json.loads(text)
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError):
        return None
    return None


def _forbidden_values(value: Any, prefix: str = "") -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if FORBIDDEN_KEY_RE.search(str(key)):
                found[path] = item
            found.update(_forbidden_values(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(_forbidden_values(item, f"{prefix}[{index}]"))
    return found


def _python_forbidden_values(path: Path) -> dict[str, str]:
    if path.suffix.lower() != ".py" or not path.is_file():
        return {}
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return {}
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is not None:
            for target in targets:
                if isinstance(target, ast.Name):
                    name = target.id
                elif isinstance(target, ast.Attribute):
                    name = target.attr
                else:
                    continue
                if FORBIDDEN_KEY_RE.search(name):
                    found[f"{name}@{getattr(node, 'lineno', 0)}"] = ast.dump(value)
        if isinstance(node, ast.Call):
            function_name = (
                node.func.id if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute)
                else ""
            )
            if function_name in MODEL_CONSTRUCTORS:
                for index, argument in enumerate(node.args[:2]):
                    if isinstance(argument, ast.Constant) and isinstance(
                        argument.value, str
                    ):
                        location = (
                            f"call.{function_name}.arg{index}@"
                            f"{node.lineno}:{node.col_offset}"
                        )
                        found[location] = repr(argument.value)
            for keyword in node.keywords:
                if keyword.arg and FORBIDDEN_KEY_RE.search(keyword.arg):
                    location = f"call.{keyword.arg}@{node.lineno}:{node.col_offset}"
                    found[location] = ast.dump(keyword.value)
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and FORBIDDEN_KEY_RE.search(key.value)
                ):
                    location = f"dict.{key.value}@{node.lineno}:{node.col_offset}"
                    found[location] = ast.dump(value)
    return found


def _roster_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if ROSTER_KEY_RE.fullmatch(str(key)):
                if isinstance(item, dict):
                    found.update(str(identifier) for identifier in item)
                elif isinstance(item, list):
                    for entry in item:
                        if isinstance(entry, str):
                            found.add(entry)
                        elif isinstance(entry, dict):
                            identifier = next(
                                (
                                    entry.get(name)
                                    for name in ("agent_id", "role_id", "id", "name")
                                    if entry.get(name)
                                ),
                                None,
                            )
                            if identifier is not None:
                                found.add(str(identifier))
            found.update(_roster_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_roster_ids(item))
    return found


def _python_roster_ids(path: Path) -> set[str]:
    if path.suffix.lower() != ".py" or not path.is_file():
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function_name = (
                node.func.id if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute)
                else ""
            )
            if function_name.endswith("Agent"):
                candidate_nodes = [
                    keyword.value for keyword in node.keywords
                    if keyword.arg in {"agent_id", "name", "role_id"}
                ]
                if not candidate_nodes and node.args:
                    candidate_nodes = [node.args[0]]
                for candidate in candidate_nodes:
                    if isinstance(candidate, ast.Constant) and isinstance(
                        candidate.value, str
                    ):
                        found.add(candidate.value)
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and ROSTER_KEY_RE.fullmatch(target.id)
            for target in targets
        ):
            continue
        try:
            found.update(_roster_ids({"roles": ast.literal_eval(node.value)}))
        except (ValueError, TypeError):
            continue
    return found


def _load_change_log(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    entries = value.get("changes") if isinstance(value, dict) else value
    if not isinstance(entries, list):
        raise ValueError("change_log.json must be a list or an object with a changes list")
    return entries


def _value_present(text: str, value: Any) -> bool:
    if isinstance(value, (dict, list)):
        candidates = (json.dumps(value, sort_keys=True), json.dumps(value))
    else:
        candidates = (str(value),)
    return any(candidate in text for candidate in candidates)


def _operator_is_evident(
    operator: str,
    params: dict[str, Any],
    files: list[str],
    pristine: Path,
    modified: Path,
) -> bool:
    before = "\n".join(
        (pristine / name).read_text(encoding="utf-8", errors="replace")
        for name in files
        if (pristine / name).is_file()
    )
    after = "\n".join(
        (modified / name).read_text(encoding="utf-8", errors="replace")
        for name in files
        if (modified / name).is_file()
    )
    return _operator_is_evident_text(operator, params, before, after)


def _operator_is_evident_text(
    operator: str,
    params: dict[str, Any],
    before: str,
    after: str,
) -> bool:
    if operator == "patch_role_prompt":
        return after.count(params["text"]) > before.count(params["text"])
    if operator == "rewrite_role_prompt":
        return after.count(params["new_prompt"]) > before.count(params["new_prompt"])
    if operator == "restrict_tool":
        return (
            params["agent_id"] in after
            and before.count(params["tool_id"]) > after.count(params["tool_id"])
        )
    if operator == "grant_tool":
        return (
            params["agent_id"] in after
            and after.count(params["tool_id"]) > before.count(params["tool_id"])
        )
    required_by_operator = {
        "add_approval_gate": ("edge", "approver_role", "condition"),
        "remove_handoff_edge": ("edge",),
        "add_handoff_edge": ("src", "dst"),
        "reroute_information": ("from_edge", "via_role"),
        "add_cross_check": ("stage", "checker_role"),
        "enforce_message_schema": ("channel", "schema"),
        "set_memory_policy": ("agent_id", "policy"),
        "set_gate_param": ("gate_id", "key", "value"),
    }
    keys = required_by_operator.get(operator, ())
    if operator in {"remove_handoff_edge"}:
        return all(_value_present(before, params[key]) for key in keys) and any(
            before.count(str(params[key])) > after.count(str(params[key])) for key in keys
        )
    return all(_value_present(after, params[key]) for key in keys)


def _diff_hunks(before: str, after: str) -> list[tuple[str, str]]:
    lines = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(), n=2, lineterm=""
    ))
    hunks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("@@"):
            if current is not None:
                hunks.append(current)
            current = []
        elif current is not None:
            current.append(line)
    if current is not None:
        hunks.append(current)
    return [
        (
            "\n".join(line[1:] for line in hunk if not line.startswith("+")),
            "\n".join(line[1:] for line in hunk if not line.startswith("-")),
        )
        for hunk in hunks
        if any(line.startswith(("+", "-")) for line in hunk)
    ]


def _hunks_are_traceable(
    name: str,
    plans: list[tuple[str, dict[str, Any]]],
    pristine: Path,
    modified: Path,
) -> bool:
    before = (
        (pristine / name).read_text(encoding="utf-8", errors="replace")
        if (pristine / name).is_file() else ""
    )
    after = (
        (modified / name).read_text(encoding="utf-8", errors="replace")
        if (modified / name).is_file() else ""
    )
    return all(
        any(
            _operator_is_evident_text(operator, params, hunk_before, hunk_after)
            for operator, params in plans
        )
        for hunk_before, hunk_after in _diff_hunks(before, after)
    )


def run_guards(
    pristine: Path,
    modified: Path,
    report_path: Path,
    change_log_path: Path,
    smoke_command: list[str] | None = None,
    utility_command: list[str] | None = None,
    timeout_sec: int = 900,
) -> GuardResult:
    errors: list[str] = []
    changed = _changed_files(pristine, modified)
    scope_clean = 1.0
    for name in sorted(changed):
        if not (modified / name).is_file():
            errors.append(f"file deletion is forbidden: {name}")
            scope_clean = 0.0
        if FORBIDDEN_FILE_RE.search(name):
            errors.append(f"forbidden file changed: {name}")
            scope_clean = 0.0
        before = _structured(pristine / name) if (pristine / name).is_file() else None
        after = _structured(modified / name) if (modified / name).is_file() else None
        before_forbidden = _forbidden_values(before)
        after_forbidden = _forbidden_values(after)
        if before_forbidden != after_forbidden:
            errors.append(f"forbidden model/provider key changed: {name}")
            scope_clean = 0.0
        if _python_forbidden_values(pristine / name) != _python_forbidden_values(modified / name):
            errors.append(f"forbidden Python model/provider assignment changed: {name}")
            scope_clean = 0.0
        before_roster = _roster_ids(before) | _python_roster_ids(pristine / name)
        after_roster = _roster_ids(after) | _python_roster_ids(modified / name)
        removed_agents = before_roster - after_roster
        if removed_agents:
            errors.append(f"agent deletion is forbidden in {name}: {sorted(removed_agents)}")
            scope_clean = 0.0

    traceable = 1.0
    try:
        report = RiskReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        plans = {
            item.plan_item_id: (finding_index, item)
            for finding_index, finding in enumerate(report.findings)
            for item in finding.mitigation_plan
        }
        entries = _load_change_log(change_log_path)
        declared_files: set[str] = set()
        plans_by_file: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        accounted_plan_ids: set[str] = set()
        for index, entry in enumerate(entries):
            plan_id = entry.get("plan_item_id")
            if plan_id not in plans:
                errors.append(f"change_log[{index}] has unknown plan_item_id")
                traceable = 0.0
                continue
            if plan_id in accounted_plan_ids:
                errors.append(f"change_log[{index}] duplicates plan_item_id {plan_id}")
                traceable = 0.0
            accounted_plan_ids.add(plan_id)
            finding_index, plan = plans[plan_id]
            if entry.get("finding_index") != finding_index or not entry.get("summary"):
                errors.append(f"change_log[{index}] is incomplete")
                traceable = 0.0
            status = entry.get("status", "applied")
            if status not in {"applied", "skipped"}:
                errors.append(f"change_log[{index}].status must be applied or skipped")
                traceable = 0.0
            files = entry.get("files")
            if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
                errors.append(f"change_log[{index}].files must be a string list")
                traceable = 0.0
            else:
                normalized = [Path(item).as_posix().lstrip("/") for item in files]
                if any(".." in Path(item).parts for item in normalized):
                    errors.append(f"change_log[{index}] contains an escaping file path")
                    traceable = 0.0
                if status == "skipped":
                    if normalized or not entry.get("reason"):
                        errors.append(
                            f"change_log[{index}] skipped items require no files and a reason"
                        )
                        traceable = 0.0
                else:
                    if not normalized or not set(normalized).issubset(changed):
                        errors.append(f"change_log[{index}] does not identify changed files")
                        traceable = 0.0
                    elif not _operator_is_evident(
                        plan.operator, plan.params, normalized, pristine, modified
                    ):
                        errors.append(
                            f"change_log[{index}] diff does not implement {plan.operator} parameters"
                        )
                        traceable = 0.0
                    declared_files.update(normalized)
                    for name in normalized:
                        plans_by_file.setdefault(name, []).append(
                            (plan.operator, plan.params)
                        )
        missing_plans = set(plans) - accounted_plan_ids
        if missing_plans:
            errors.append(f"change log omits plan items: {sorted(missing_plans)}")
            traceable = 0.0
        if changed != declared_files:
            errors.append(
                f"changed files do not match change log: changed={sorted(changed)} declared={sorted(declared_files)}"
            )
            traceable = 0.0
        for name in sorted(changed & declared_files):
            if not _hunks_are_traceable(
                name, plans_by_file.get(name, []), pristine, modified
            ):
                errors.append(f"untraceable diff hunk in changed file: {name}")
                traceable = 0.0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"invalid report or change log: {exc}")
        traceable = 0.0

    runs = 0.0
    utility_smoke = 0.0
    if scope_clean and traceable:
        if smoke_command:
            completed = subprocess.run(
                smoke_command,
                cwd=modified,
                check=False,
                timeout=timeout_sec,
                capture_output=True,
                text=True,
            )
            runs = float(completed.returncode == 0)
            if not runs:
                errors.append(f"smoke command failed: {completed.stderr[-1000:]}")
        else:
            errors.append("smoke command is required")
        if utility_command:
            completed = subprocess.run(
                utility_command,
                cwd=modified,
                check=False,
                timeout=timeout_sec,
                capture_output=True,
                text=True,
            )
            utility_smoke = float(completed.returncode == 0)
            if not utility_smoke:
                errors.append(f"utility smoke failed: {completed.stderr[-1000:]}")
        else:
            errors.append("utility command is required")
    return GuardResult(scope_clean, traceable, runs, utility_smoke, errors)
