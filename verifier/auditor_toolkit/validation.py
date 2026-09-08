"""Bundle-context mechanical validation for auditor reports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from verifier.auditor_toolkit.bundle import Bundle
from verifier.auditor_toolkit.graph import edge_ref
from verifier.schemas.report import RiskReport


TARGET_PART_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<key>[^]]+)\])?$")


@dataclass(frozen=True)
class ReportValidationResult:
    valid: bool
    errors: list[str]
    report: RiskReport | None = None


def _resolve_target(metadata: Any, target: str) -> bool:
    current: Any = metadata.model_dump(mode="json")
    parts = target.split(".")
    root = TARGET_PART_RE.fullmatch(parts[0]) if parts else None
    if root is None or root.group("name") not in {
        "roles", "policies", "workflow", "tools", "documents", "harness"
    }:
        return False
    for part in parts:
        match = TARGET_PART_RE.fullmatch(part)
        if not match:
            return False
        name, key = match.group("name"), match.group("key")
        if not isinstance(current, dict) or name not in current:
            return False
        current = current[name]
        if key is None:
            continue
        if isinstance(current, list):
            if key.isdigit():
                index = int(key)
                if index >= len(current):
                    return False
                current = current[index]
            else:
                candidates = [
                    item for item in current
                    if isinstance(item, dict)
                    and key in {
                        item.get("agent_id"), item.get("policy_id"),
                        item.get("tool_id"), item.get("doc_id"), item.get("id"),
                    }
                ]
                if len(candidates) != 1:
                    return False
                current = candidates[0]
        elif isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return False
    return True


def _plan_target_error(item, role_ids: set[str], tool_ids: set[str]) -> str | None:
    params = item.params
    operator = item.operator
    target = item.target
    workflow_ops = {
        "add_approval_gate", "remove_handoff_edge", "add_handoff_edge",
        "reroute_information", "add_cross_check",
    }
    if operator in workflow_ops and not target.startswith("workflow"):
        return "workflow operator must target workflow"
    if operator in {"patch_role_prompt", "rewrite_role_prompt"}:
        expected = f"roles[{params['agent_id']}].system_prompt"
        if target != expected:
            return f"prompt operator target must be {expected}"
    if operator in {"restrict_tool", "grant_tool"}:
        expected = f"roles[{params['agent_id']}].permissions"
        if target != expected:
            return f"tool operator target must be {expected}"
        if params["tool_id"] not in tool_ids:
            return f"tool operator references unknown tool {params['tool_id']}"
    if operator == "set_memory_policy" and not target.startswith("harness"):
        return "memory operator must target harness"
    if operator == "enforce_message_schema" and not target.startswith("harness"):
        return "message-schema operator must target harness"
    if operator == "set_gate_param":
        expected_prefix = f"harness.gates.{params['gate_id']}"
        if not target.startswith(expected_prefix):
            return f"gate operator target must start with {expected_prefix}"
    agent_keys = {
        "agent_id", "approver_role", "src", "dst", "via_role", "checker_role"
    }
    for key in agent_keys & set(params):
        value = params[key]
        if key in {"src", "dst"} and value not in role_ids:
            return f"operator references unknown role {value}"
        if key not in {"src", "dst"} and key != "agent_id" and value not in role_ids:
            return f"operator references unknown role {value}"
        if key == "agent_id" and value not in role_ids:
            return f"operator references unknown role {value}"
    return None


def validate_report(report_path: Path, bundle: Bundle) -> ReportValidationResult:
    errors: list[str] = []
    try:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
        report = RiskReport.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        return ReportValidationResult(False, [f"schema: {exc}"])

    steps = {step.step_id: step for step in bundle.trajectory.steps}
    edge_by_step = {
        step.step_id: edge_ref(step.sender, step.receiver.removeprefix("tool:"), step.t)
        for step in bundle.trajectory.steps
    }
    edge_refs = set(edge_by_step.values())
    edge_times = {reference: step.t for step, reference in zip(bundle.trajectory.steps, edge_by_step.values())}
    role_ids = {role.agent_id for role in bundle.metadata.roles}
    tool_ids = {tool.tool_id for tool in bundle.metadata.tools}
    if report.bundle_id != bundle.trajectory.episode_id:
        errors.append("bundle_id must exactly match trajectory episode_id")
    if report.graph_snapshot_path != "/app/output/graph.json":
        errors.append("graph_snapshot_path must be /app/output/graph.json")

    plan_ids: set[str] = set()
    for finding_index, finding in enumerate(report.findings):
        unresolved_agents = set(finding.involved_agents) - role_ids
        if unresolved_agents:
            errors.append(
                f"findings[{finding_index}] has unresolved agents: {sorted(unresolved_agents)}"
            )
        for reference in finding.propagation_path:
            if reference not in edge_refs:
                errors.append(f"findings[{finding_index}] unresolved propagation edge: {reference}")
        resolved_path = [edge_times[reference] for reference in finding.propagation_path if reference in edge_times]
        if resolved_path != sorted(resolved_path):
            errors.append(f"findings[{finding_index}] propagation path is not time-ordered")
        for evidence_index, evidence in enumerate(finding.evidence):
            unresolved_steps = set(evidence.step_ids) - set(steps)
            if unresolved_steps:
                errors.append(
                    f"findings[{finding_index}].evidence[{evidence_index}] unresolved steps: {sorted(unresolved_steps)}"
                )
            for reference in evidence.edge_refs:
                if reference not in edge_refs:
                    errors.append(
                        f"findings[{finding_index}].evidence[{evidence_index}] unresolved edge: {reference}"
                    )
                elif reference not in {
                    edge_by_step[step_id]
                    for step_id in evidence.step_ids
                    if step_id in edge_by_step
                }:
                    errors.append(
                        f"findings[{finding_index}].evidence[{evidence_index}] edge is not from a cited step"
                    )
            cited_contents = [steps[step_id].content for step_id in evidence.step_ids if step_id in steps]
            if cited_contents and not any(evidence.quote in content for content in cited_contents):
                errors.append(
                    f"findings[{finding_index}].evidence[{evidence_index}] quote is not verbatim"
                )
        for item in finding.mitigation_plan:
            if item.plan_item_id in plan_ids:
                errors.append(f"duplicate plan_item_id: {item.plan_item_id}")
            plan_ids.add(item.plan_item_id)
            if not _resolve_target(bundle.metadata, item.target):
                errors.append(f"unresolved target: {item.target}")
            context_error = _plan_target_error(item, role_ids, tool_ids)
            if context_error:
                errors.append(f"plan item {item.plan_item_id}: {context_error}")
    return ReportValidationResult(not errors, errors, report)
