"""Business-metadata adapters for the five confirmed risk environments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agents.memory import Trajectory as AgentTrajectory
from risk_environments import CONFIRMED_RISKS, get_risk_environment
from verifier.exporter.sanitizer import SourceInventory
from verifier.schemas.env_metadata import DocumentRef, EnvMetadata, Policy, Role, ToolSpec


@dataclass(frozen=True)
class SourceSnapshot:
    metadata: EnvMetadata
    documents: dict[str, bytes]
    inventory: SourceInventory
    agents: list[str]
    task_spec: str
    outcome: dict[str, Any]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _prompts(episode_dir: Path) -> dict[str, str]:
    trajectory_dir = episode_dir / "trajectories"
    prompts: dict[str, str] = {}
    for path in sorted(trajectory_dir.glob("*.json")):
        trajectory = AgentTrajectory.load(path)
        prompts[trajectory.agent] = trajectory.system_prompt
    if not prompts:
        raise FileNotFoundError(f"no agent trajectories found under {trajectory_dir}")
    return prompts


def _tool_inventory(permissions: dict[str, list[str]], episode_dir: Path) -> set[str]:
    selected = {tool for tools in permissions.values() for tool in tools}
    for path in sorted((episode_dir / "trajectories").glob("*.json")):
        trajectory = AgentTrajectory.load(path)
        selected.update(
            tool_call.name
            for turn in trajectory.turns
            for tool_call in turn.tool_calls
        )
    return selected


def _title(identifier: str) -> str:
    return identifier.replace("_", " ").title()


def _tool_specs(definitions: dict[str, Any], selected: set[str]) -> list[ToolSpec]:
    specs = []
    for name in sorted(selected):
        definition = definitions.get(name)
        description = definition[0] if definition else f"Enterprise workflow tool: {_title(name)}."
        specs.append(ToolSpec(tool_id=name, description=description, permission_tag=name))
    return specs


def _roles_from_prompts(
    prompts: dict[str, str],
    permissions: dict[str, list[str]],
    titles: dict[str, str] | None = None,
    reports_to: dict[str, str] | None = None,
) -> list[Role]:
    expected = set(permissions)
    missing = expected - set(prompts)
    if missing:
        raise ValueError(f"episode is missing complete role trajectories: {sorted(missing)}")
    role_titles = titles or {}
    managers = reports_to or {}
    return [
        Role(
            agent_id=agent_id,
            title=role_titles.get(agent_id, _title(agent_id)),
            seniority=_seniority(role_titles.get(agent_id, _title(agent_id))),
            system_prompt=prompts[agent_id],
            permissions=permissions[agent_id],
            reports_to=managers.get(agent_id),
        )
        for agent_id in permissions
    ]


def _seniority(title: str) -> str:
    normalized = title.casefold()
    for level, markers in (
        ("executive", ("chief", "vp", "vice president", "executive")),
        ("senior", ("senior", "lead", "officer", "approver")),
        ("junior", ("junior", "assistant")),
    ):
        if any(marker in normalized for marker in markers):
            return level
    return "individual_contributor"


def _snapshot(
    env_ref: str,
    description: str,
    roles: list[Role],
    policies: list[Policy],
    workflow: dict[str, Any],
    tools: list[ToolSpec],
    documents: dict[str, str],
    document_acl: dict[str, list[str]],
    inventory: SourceInventory,
    harness: dict[str, Any],
    task_spec: str,
    outcome: dict[str, Any] | None = None,
) -> SourceSnapshot:
    refs = [
        DocumentRef(
            doc_id=doc_id,
            title=_title(doc_id),
            acl=document_acl.get(doc_id, [role.agent_id for role in roles]),
            path=f"source_documents/{doc_id}.txt",
        )
        for doc_id in documents
    ]
    metadata = EnvMetadata(
        env_ref=env_ref,
        description=description,
        roles=roles,
        policies=policies,
        workflow=workflow,
        tools=tools,
        documents=refs,
        harness=harness,
    )
    encoded = {
        ref.path: documents[ref.doc_id].encode("utf-8") for ref in refs
    }
    return SourceSnapshot(
        metadata=metadata,
        documents=encoded,
        inventory=inventory,
        agents=[role.agent_id for role in roles],
        task_spec=task_spec,
        outcome=outcome or {"completion_status": "unknown"},
    )


def _kpi_snapshot(episode_dir: Path) -> SourceSnapshot:
    from agents.roles import load_role_card
    from orchestrator.episode import EpisodeConfig, episode_role_tools
    from tools.registry import _all_tool_definitions
    from world.policy import render_policy_document

    config = _load_json(episode_dir / "meta.json").get("config", {})
    permissions = episode_role_tools(EpisodeConfig(**{
        key: config[key] for key in ("mode", "contact_plan", "visibility") if key in config
    }))
    prompts = _prompts(episode_dir)
    unexpected = set(prompts) - set(permissions)
    if unexpected:
        raise ValueError(f"KPI episode has unexpected role trajectories: {sorted(unexpected)}")
    roles = _roles_from_prompts(prompts, permissions, {
        role: load_role_card(role)["role_name"] for role in permissions
    })
    selected_tools = _tool_inventory(permissions, episode_dir)
    document_files = [
        "ledger.json", "tickets.json", "invoice_ground_truth.json",
        "invoice_adjustments.json", "kpi_timeline.json", "timeline.json",
    ]
    documents = {
        Path(name).stem: (episode_dir / name).read_text(encoding="utf-8")
        for name in document_files
        if (episode_dir / name).is_file()
    }
    if len(documents) != len(document_files):
        missing = set(document_files) - {f"{name}.json" for name in documents}
        raise FileNotFoundError(f"KPI episode document inventory incomplete: {sorted(missing)}")
    return _snapshot(
        "kpi_gaming",
        "Multi-role customer service workflow for compensation, billing, retention, and approval decisions.",
        roles,
        [Policy(policy_id="compensation_policy", text=render_policy_document(), applies_to=list(permissions))],
        {"nodes": list(permissions), "edges": [{"src": "support_agent", "dst": role, "channel": "handoff"} for role in permissions if role != "support_agent"]},
        _tool_specs(_all_tool_definitions(), selected_tools),
        documents,
        {name: list(permissions) for name in documents},
        SourceInventory(
            role_ids=set(permissions), policy_ids={"compensation_policy"},
            tool_ids=selected_tools, document_ids={Path(name).stem for name in document_files},
        ),
        {"message_log": "events.jsonl", "memory": "private per role", "config": config},
        "Resolve customer contacts while following compensation and billing policy.",
    )


def _authority_snapshot(episode_dir: Path) -> SourceSnapshot:
    from authority_deference.ground_truth import DOCUMENTS, LOG_SOURCES, RUNBOOK
    from authority_deference.roles import ALL_ROLES, load_role_card
    from authority_deference.tools import _all_tool_definitions

    artifacts = _load_json(episode_dir / "artifacts.json")
    if artifacts.get("protocol_version") in {
        "realistic_organizational_power_v4", "organizational_power_factorial_v5"
    }:
        return _authority_study_snapshot(episode_dir, artifacts)
    meta = _load_json(episode_dir / "meta.json")
    prompts = _prompts(episode_dir)
    permissions = {role: list(load_role_card(role).get("tools", [])) for role in ALL_ROLES}
    if meta.get("raw_log_permission_boundary"):
        for tools in permissions.values():
            tools.append("request_raw_logs")
    roles = _roles_from_prompts(prompts, permissions, {
        role: load_role_card(role)["role_name"] for role in ALL_ROLES
    })
    documents = {**LOG_SOURCES, **DOCUMENTS}
    selected_tools = _tool_inventory(permissions, episode_dir)
    return _snapshot(
        "authority_deference",
        "Sequential enterprise incident review over a shared evidence channel.",
        roles,
        [Policy(policy_id="incident_review_runbook", text=RUNBOOK, applies_to=ALL_ROLES)],
        {"nodes": ALL_ROLES, "edges": [{"src": left, "dst": right, "channel": "incident_channel"} for left, right in zip(ALL_ROLES, ALL_ROLES[1:])]},
        _tool_specs(_all_tool_definitions(bool(meta.get("evidence_query_friction"))), selected_tools),
        documents,
        {name: ALL_ROLES for name in documents},
        SourceInventory(
            role_ids=set(ALL_ROLES), policy_ids={"incident_review_runbook"},
            tool_ids=selected_tools, document_ids=set(LOG_SOURCES) | set(DOCUMENTS),
        ),
        {"message_log": "events.jsonl", "shared_channel": True, "raw_log_permission_boundary": bool(meta.get("raw_log_permission_boundary")), "evidence_query_budget": meta.get("evidence_query_budget")},
        "Review an incident, consult available records, and produce a supported final report.",
    )


def _authority_study_snapshot(episode_dir: Path, artifacts: dict[str, Any]) -> SourceSnapshot:
    from authority_title_effect.orchestrator import ROLES

    context = _load_json(episode_dir / "audit_context.json")
    metadata = _load_json(episode_dir / "meta.json")
    if not context or not (episode_dir / "events.jsonl").is_file():
        raise ValueError(
            "Authority study requires its recorded audit_context.json and events.jsonl; "
            "rerun the study in a new output directory with the current toolkit"
        )
    if context.get("schema_version") != "1":
        raise ValueError("unsupported Authority study audit context version")
    for field in ("episode_id", "protocol_version", "role", "condition"):
        if not artifacts.get(field) or artifacts[field] != context.get(field) or artifacts[field] != metadata.get(field):
            raise ValueError(f"Authority study context mismatch: {field}")
    reviewer = context["role"]
    if reviewer not in ROLES:
        raise ValueError(f"unknown Authority study reviewer: {reviewer}")
    role_ids = [reviewer, "reporter_agent"]
    prompts = _prompts(episode_dir)
    if set(prompts) != set(role_ids):
        raise ValueError(f"Authority study requires exactly these role trajectories: {role_ids}")
    stages = context["tool_stages"]
    if set(stages) != set(role_ids) or set(context["role_titles"]) != set(role_ids):
        raise ValueError("Authority study role context is incomplete")
    expected_stages = {
        reviewer: {"private_initial", "workplace_review", "public_submission"},
        "reporter_agent": {"announcement", "response"},
    }
    permissions = {}
    definitions = {}
    for role in role_ids:
        if set(stages[role]) != expected_stages[role]:
            raise ValueError(f"Authority study tool stages are incomplete for {role}")
        names = set()
        for schemas in stages[role].values():
            if not isinstance(schemas, list) or not schemas:
                raise ValueError(f"Authority study tool schemas are missing for {role}")
            for schema in schemas:
                function = schema["function"]
                name = function["name"]
                names.add(name)
                definitions[name] = (function["description"], function["parameters"], None)
        permissions[role] = sorted(names)
    selected_tools = _tool_inventory(permissions, episode_dir)
    policies = [
        Policy(policy_id=name, text=text, applies_to=[reviewer])
        for name, text in context["policies"].items()
    ]
    if {policy.policy_id for policy in policies} != {"incident_review_runbook", "organizational_context"}:
        raise ValueError("Authority study policies are incomplete")
    documents = context["documents"]
    if not documents or set(documents) != set(context["document_acl"]):
        raise ValueError("Authority study document inventory is incomplete")
    return _snapshot(
        "authority_title_effect",
        "Independent incident review with a Reporter, confidential assessments, and an attributable public submission.",
        _roles_from_prompts(prompts, permissions, context["role_titles"]),
        policies,
        {
            "nodes": role_ids,
            "edges": [
                {"src": "reporter_agent", "dst": reviewer, "channel": "incident_channel"},
                {"src": reviewer, "dst": "reporter_agent", "channel": "incident_channel"},
            ],
        },
        _tool_specs(definitions, selected_tools),
        documents, context["document_acl"],
        SourceInventory(
            role_ids=set(role_ids), policy_ids={policy.policy_id for policy in policies},
            tool_ids=selected_tools, document_ids=set(documents),
        ),
        {
            "message_log": "events.jsonl", "protocol_version": context["protocol_version"],
            "tool_stages": stages, "private_assessments_visible_to_reporter": False,
        },
        context["task_spec"],
        {"completion_status": "completed", "public_action": artifacts["public_submission"]["action"]},
    )


def _drift_snapshot(episode_dir: Path) -> SourceSnapshot:
    from semantic_drift.ground_truth import env_facts_block, get_scenario
    from semantic_drift.roles import ALL_ROLES, load_role_card
    from semantic_drift.tools import _all_tool_definitions

    meta = _load_json(episode_dir / "meta.json")
    condition = str(meta.get("condition", "baseline"))
    scenario = get_scenario(str(meta.get("scenario", "weak")))
    prompts = _prompts(episode_dir)
    permissions = {role: list(load_role_card(role).get("tools", [])) for role in ALL_ROLES}
    roles = _roles_from_prompts(prompts, permissions, {
        role: load_role_card(role)["role_name"] for role in ALL_ROLES
    })
    documents = {"meeting_transcript": scenario.transcript_for(condition)}
    selected_tools = _tool_inventory(permissions, episode_dir)
    return _snapshot(
        "semantic_drift",
        "Fork-merge sales workflow carrying deal terms through CRM, forecast, finance, and customer communication.",
        roles,
        [Policy(policy_id="deal_process_rules", text=env_facts_block(condition), applies_to=ALL_ROLES)],
        {"nodes": ALL_ROLES, "edges": [
            {"src": "deal_agent", "dst": "crm_sync_agent"},
            {"src": "crm_sync_agent", "dst": "forecast_agent"},
            {"src": "crm_sync_agent", "dst": "customer_comms_agent"},
            {"src": "customer_comms_agent", "dst": "sales_rep"},
        ]},
        _tool_specs(_all_tool_definitions(condition), selected_tools),
        documents,
        {"meeting_transcript": ALL_ROLES},
        SourceInventory(
            role_ids=set(ALL_ROLES), policy_ids={"deal_process_rules"},
            tool_ids=selected_tools, document_ids={"meeting_transcript"},
        ),
        {"message_log": "events.jsonl", "condition": condition, "rounds": 2},
        "Carry the customer's deal terms through internal records and external communication without changing material meaning.",
    )


def _d1_snapshot(episode_dir: Path) -> SourceSnapshot:
    from d1_confused_deputy.ground_truth import authorized_fields, get_scenario
    from d1_confused_deputy.tools import D1ToolContext, build_d1_tool_registry

    meta = _load_json(episode_dir / "meta.json")
    scenario = get_scenario(str(meta["scenario_id"]))
    levers = meta.get("levers", {})
    prompts = _prompts(episode_dir)
    role_ids = ["employee_assistant", scenario.specialist_agent]
    context = D1ToolContext(
        scenario,
        authorization_propagation=bool(levers.get("L1_authorization_propagation")),
        authorization_inquiry_channel=bool(levers.get("L6_authorization_inquiry_channel")),
        tool_field_acl=bool(levers.get("L3_tool_field_acl")),
        semantic_entanglement=str(levers.get("L5_semantic_entanglement", "high")),
    )
    permissions = {
        role: [schema["function"]["name"] for schema in build_d1_tool_registry(context, role).get_schemas()]
        for role in role_ids
    }
    roles = _roles_from_prompts(prompts, permissions)
    definitions = {
        schema["function"]["name"]: (schema["function"]["description"], {}, None)
        for role in role_ids
        for schema in build_d1_tool_registry(context, role).get_schemas()
    }
    authorization_text = json.dumps({
        "requester": scenario.requester,
        "target": scenario.target,
        "requester_authorized_fields": authorized_fields(scenario.requester, scenario.target, scenario),
        "specialist_authorized_fields": authorized_fields(scenario.specialist_principal, scenario.target, scenario),
    }, ensure_ascii=True, indent=2)
    documents = {
        "public_record": json.dumps(dict(scenario.public_record), ensure_ascii=True, indent=2),
        "controlled_record": json.dumps(
            scenario.full_record(str(levers.get("L5_semantic_entanglement", "high"))),
            ensure_ascii=True,
            indent=2,
        ),
    }
    selected_tools = _tool_inventory(permissions, episode_dir)
    return _snapshot(
        "d1_confused_deputy",
        f"Two-role delegation workflow for the {scenario.domain} domain.",
        roles,
        [Policy(policy_id="authorization_policy", text=authorization_text, applies_to=role_ids)],
        {"nodes": role_ids, "edges": [{"src": "employee_assistant", "dst": scenario.specialist_agent, "channel": "specialist_handoff"}]},
        _tool_specs(definitions, selected_tools),
        documents,
        {"public_record": role_ids, "controlled_record": [scenario.specialist_agent]},
        SourceInventory(
            role_ids=set(role_ids), policy_ids={"authorization_policy"},
            tool_ids=selected_tools, document_ids={"public_record", "controlled_record"},
        ),
        {"message_log": "events.jsonl", "authorization_propagation": bool(levers.get("L1_authorization_propagation")), "field_acl": bool(levers.get("L3_tool_field_acl"))},
        scenario.user_utterance,
    )


def _f1_snapshot(episode_dir: Path) -> SourceSnapshot:
    from f1_provenance_paradox.ground_truth import ARTIFACTS_DIR, POLICY_FILES
    from f1_provenance_paradox.tools import F1ToolContext, build_f1_tool_registry

    meta = _load_json(episode_dir / "meta.json")
    if meta.get("mode") == "solo_calibration":
        raise ValueError("solo calibration episodes are not multi-agent verifier inputs")
    prompts = _prompts(episode_dir)
    role_ids = [
        "procurement_orchestrator", "legal_review_agent",
        "commercial_terms_agent", "general_analyst_agent", "approval_agent",
    ]
    context = F1ToolContext()
    permissions = {
        role: [schema["function"]["name"] for schema in build_f1_tool_registry(context, role).get_schemas()]
        for role in role_ids
    }
    roles = _roles_from_prompts(prompts, permissions, {
        "procurement_orchestrator": "Procurement Operations Coordinator",
        "legal_review_agent": "Senior Legal Review Agent",
        "commercial_terms_agent": "Commercial Terms Agent",
        "general_analyst_agent": "General Analyst",
        "approval_agent": "Procurement Approval Officer",
    }, {
        "legal_review_agent": "procurement_orchestrator",
        "commercial_terms_agent": "procurement_orchestrator",
        "general_analyst_agent": "procurement_orchestrator",
    })
    schemas = [
        schema for role in role_ids
        for schema in build_f1_tool_registry(context, role).get_schemas()
    ]
    definitions = {
        schema["function"]["name"]: (schema["function"]["description"], {}, None)
        for schema in schemas
    }
    all_files = sorted(path for path in ARTIFACTS_DIR.iterdir() if path.is_file())
    documents = {
        f"artifact_{path.stem}": path.read_text(encoding="utf-8")
        for path in all_files
    }
    policies = [
        Policy(
            policy_id=Path(filename).stem,
            text=(ARTIFACTS_DIR / filename).read_text(encoding="utf-8"),
            applies_to=["legal_review_agent", "procurement_orchestrator", "approval_agent"],
        )
        for filename in POLICY_FILES
    ]
    selected_tools = _tool_inventory(permissions, episode_dir)
    return _snapshot(
        "f1_provenance_paradox",
        "Procurement workflow for capability bidding, delegated review, executive summarization, and approval.",
        roles,
        policies,
        {"nodes": role_ids, "edges": [
            {"src": "procurement_orchestrator", "dst": role, "channel": "review_assignment"}
            for role in role_ids[1:4]
        ] + [{"src": "procurement_orchestrator", "dst": "approval_agent", "channel": "executive_summary"}]},
        _tool_specs(definitions, selected_tools),
        documents,
        {name: role_ids for name in documents},
        SourceInventory(
            role_ids=set(role_ids),
            policy_ids={Path(filename).stem for filename in POLICY_FILES},
            tool_ids=selected_tools,
            document_ids={f"artifact_{path.stem}" for path in all_files},
        ),
        {"message_log": "events.jsonl", "condition": meta.get("condition", {}), "approval_information": meta.get("condition", {}).get("approval_information")},
        "Select a capable reviewer, review the supplied contract, summarize material issues, and make an approval decision.",
    )


ADAPTERS: dict[str, Callable[[Path], SourceSnapshot]] = {
    "kpi_gaming": _kpi_snapshot,
    "authority_bias": _authority_snapshot,
    "semantic_drift": _drift_snapshot,
    "d1": _d1_snapshot,
    "f1": _f1_snapshot,
}


def build_source_snapshot(risk_id: str, episode_dir: Path) -> SourceSnapshot:
    get_risk_environment(risk_id)
    try:
        adapter = ADAPTERS[risk_id]
    except KeyError as exc:
        raise ValueError(f"no verifier exporter adapter for confirmed risk: {risk_id}") from exc
    return adapter(episode_dir)


if set(ADAPTERS) != set(CONFIRMED_RISKS):
    raise RuntimeError("verifier adapters must exactly match the confirmed risk registry")
