import json
from pathlib import Path

import pytest

from verifier.auditor_toolkit.bundle import Bundle
from verifier.exporter.adapters import build_source_snapshot
from verifier.exporter.export import export_episode_bundle
from verifier.orchestrator.materialize import materialize_auditor_task
from verifier.schemas.sanitize_manifest import SanitizeManifest


def _a1_episode(root: Path, condition: str, role: str = "sre_agent"):
    from authority_title_effect.orchestrator import (
        RealisticPowerTitleEffectEpisodeOrchestrator, TitleEffectEpisodeConfig,
    )
    from run_authority_title_effect import build_power_mock_llms

    reviewer, reporter = build_power_mock_llms(
        deterministic_reporter_announcement=condition in "EFGH"
    )
    orchestrator = RealisticPowerTitleEffectEpisodeOrchestrator(
        llm=reviewer, reporter_llm=reporter,
        config=TitleEffectEpisodeConfig(role=role, condition=condition, provider="mock"),
        run_dir=root, episode_id=f"{role}_{condition}_seed42",
    )
    artifacts = orchestrator.run()
    return orchestrator, artifacts


@pytest.mark.parametrize("condition", list("ABCDEFGH"))
def test_a1_study_records_actual_global_events_and_role_specific_context(tmp_path, condition):
    orchestrator, artifacts = _a1_episode(tmp_path / "runs", condition)
    episode = orchestrator.episode_dir
    metadata = json.loads((episode / "meta.json").read_text(encoding="utf-8"))
    context = json.loads((episode / "audit_context.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (episode / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert metadata["protocol_version"] == artifacts["protocol_version"]
    assert context["episode_id"] == orchestrator.episode_id
    assert set(context["role_titles"]) == {"sre_agent", "reporter_agent"}
    assert all(roles == ["sre_agent"] for roles in context["document_acl"].values())
    assert context["policies"]["organizational_context"] == orchestrator._organizational_context()
    assert [event["event_seq"] for event in events] == list(range(1, len(events) + 1))
    executed = [event for event in events if event["event_type"] == "tool_call_completed"]
    recorded = [
        call for agent in (orchestrator.agent, orchestrator.reporter)
        for turn in agent.trajectory.turns for call in turn.tool_calls
    ]
    assert len(executed) == len(recorded)
    assert any(event["payload"]["name"] == "submit_public_report" for event in executed)
    assert any(event["event_type"] == "message_published" for event in events)


@pytest.mark.parametrize("condition,role", [
    (condition, role)
    for condition in "ABCD"
    for role in ("sre_agent", "customer_support_agent", "legal_agent", "report_writer_agent")
] + [
    (condition, role)
    for condition in "EFGH"
    for role in ("sre_agent", "report_writer_agent")
])
def test_a1_selected_study_exports_through_topology_auditor_task(tmp_path, condition, role):
    from verifier.auditor_toolkit.graph import check_permission
    from verifier.auditor_toolkit.topology import build_interaction_graph
    from verifier.exporter.episode_reader import read_episode_trajectory

    orchestrator, artifacts = _a1_episode(tmp_path / "runs", condition, role)
    snapshot = build_source_snapshot("authority_bias", orchestrator.episode_dir)
    assert set(snapshot.agents) == {role, "reporter_agent"}
    assert snapshot.metadata.harness["protocol_version"] == artifacts["protocol_version"]
    trajectory = read_episode_trajectory(
        orchestrator.episode_dir, orchestrator.episode_id,
        snapshot.agents, snapshot.task_spec, snapshot.outcome,
    )
    incoming = [
        message.content for agent in (orchestrator.agent, orchestrator.reporter)
        for turn in agent.trajectory.turns for message in turn.incoming_messages
    ]
    assert all(content in [step.content for step in trajectory.steps] for content in incoming)
    assert len([step for step in trajectory.steps if step.channel == "tool_call"]) == sum(
        len(turn.tool_calls) for agent in (orchestrator.agent, orchestrator.reporter)
        for turn in agent.trajectory.turns
    )
    bundle_path, manifest_path = export_episode_bundle(
        "authority_bias", orchestrator.episode_dir, tmp_path / "bundles", tmp_path / "private"
    )
    bundle = Bundle.load(bundle_path)
    manifest = SanitizeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert check_permission(bundle, manifest.agent_ids[role], manifest.tool_ids["read_incident_record"])["allowed"]
    assert not check_permission(bundle, manifest.agent_ids["reporter_agent"], manifest.tool_ids["read_incident_record"])["allowed"]
    assert all(document.acl == [manifest.agent_ids[role]] for document in bundle.metadata.documents)
    assert build_interaction_graph(bundle)["schema_version"] == "topology-1.0"
    task = materialize_auditor_task(bundle_path, tmp_path / "auditor", None, manifest, profile="v3-topology")
    assert "topology only" in (task / "instruction.md").read_text(encoding="utf-8")
    assert Bundle.load(task / "environment" / "bundle").trajectory == bundle.trajectory


@pytest.mark.parametrize("missing_file", [
    "audit_context.json", "events.jsonl", "trajectories/reporter_agent.json",
])
def test_a1_study_export_rejects_incomplete_recording(tmp_path, missing_file):
    orchestrator, _ = _a1_episode(tmp_path / "runs", "A")
    (orchestrator.episode_dir / missing_file).unlink()
    with pytest.raises(ValueError, match="requires"):
        build_source_snapshot("authority_bias", orchestrator.episode_dir)


def test_a1_study_export_rejects_mismatched_context(tmp_path):
    orchestrator, _ = _a1_episode(tmp_path / "runs", "A")
    path = orchestrator.episode_dir / "audit_context.json"
    context = json.loads(path.read_text(encoding="utf-8"))
    context["episode_id"] = "different-episode"
    path.write_text(json.dumps(context), encoding="utf-8")
    with pytest.raises(ValueError, match="context mismatch: episode_id"):
        build_source_snapshot("authority_bias", orchestrator.episode_dir)


def _kpi_episode(root: Path, *, mode="multi_agent", contact_plan="standard", visibility="on_demand"):
    from orchestrator.episode import EpisodeConfig, EpisodeOrchestrator
    from run import build_mock_llm
    from world.enterprise import EnterpriseWorld

    config = EpisodeConfig(mode=mode, contact_plan=contact_plan, visibility=visibility)
    orchestrator = EpisodeOrchestrator(
        world=EnterpriseWorld(seed=42), llm=build_mock_llm(), config=config,
        run_dir=root, episode_id="kpi-integration",
    )
    orchestrator.run("C-001")
    return orchestrator


@pytest.mark.parametrize("mode,contact_plan,role_count", [
    ("multi_agent", "standard", 4),
    ("multi_agent", "risk_v2", 6),
    ("single_agent", "standard", 1),
])
@pytest.mark.parametrize("visibility", ["on_demand", "none"])
def test_kpi_runtime_roles_and_tools_survive_export_and_audit_task(
    tmp_path, mode, contact_plan, role_count, visibility
):
    orchestrator = _kpi_episode(tmp_path / "runs", mode=mode, contact_plan=contact_plan, visibility=visibility)
    snapshot = build_source_snapshot("kpi_gaming", orchestrator.episode_dir)
    assert len(snapshot.agents) == role_count
    assert set(snapshot.agents) == set(orchestrator.agents) == snapshot.inventory.role_ids
    for role in snapshot.metadata.roles:
        declared = {
            schema["function"]["name"]
            for schema in orchestrator.agents[role.agent_id].tools.get_schemas()
        }
        assert set(role.permissions) == declared
    bundle_path, manifest_path = export_episode_bundle(
        "kpi_gaming", orchestrator.episode_dir, tmp_path / "bundles", tmp_path / "private"
    )
    bundle = Bundle.load(bundle_path)
    assert bundle.trajectory.steps
    assert len(bundle.metadata.roles) == role_count
    manifest = SanitizeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    task = materialize_auditor_task(
        bundle_path, tmp_path / "auditor", None, manifest, profile="v3-topology"
    )
    assert (task / "tests" / "manifest.json").is_file()
    assert not (task / "environment" / "bundle" / "manifest.json").exists()


@pytest.mark.parametrize("contact_plan,missing_role", [
    ("standard", "finance_approver"), ("risk_v2", "service_recovery_agent"),
])
def test_kpi_export_still_rejects_missing_active_role(tmp_path, contact_plan, missing_role):
    orchestrator = _kpi_episode(tmp_path / "runs", contact_plan=contact_plan)
    (orchestrator.episode_dir / "trajectories" / f"{missing_role}.json").unlink()
    with pytest.raises(ValueError, match="missing complete role trajectories"):
        build_source_snapshot("kpi_gaming", orchestrator.episode_dir)


@pytest.mark.parametrize("result", [
    {"error": "permission denied"}, {"error": "unknown tool"}, {"success": True},
])
def test_observed_tool_does_not_grant_permission_and_evidence_is_preserved(tmp_path, result):
    from agents.memory import ToolCallRecord, Trajectory as AgentTrajectory, TurnRecord
    from verifier.auditor_toolkit.graph import check_permission

    orchestrator = _kpi_episode(tmp_path / "runs")
    episode = orchestrator.episode_dir
    trajectory_path = episode / "trajectories" / "support_agent.json"
    recorded = AgentTrajectory.load(trajectory_path)
    attempted = ToolCallRecord(name="audit_only_payment_tool", args={"amount": 12}, result=result)
    recorded.turns.append(TurnRecord(
        turn_id=len(recorded.turns) + 1, instruction="Permission regression fixture.",
        incoming_messages=[], tool_calls=[attempted],
    ))
    recorded.save(trajectory_path)
    events_path = episode / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line]
    event = {
        "event_seq": len(events) + 1, "episode_id": orchestrator.episode_id,
        "event_type": "tool_call_completed", "agent_id": "support_agent",
        "logical_step": len(events) + 1, "payload": attempted.model_dump(mode="json"),
    }
    with events_path.open("a", encoding="utf-8") as destination:
        destination.write(json.dumps(event) + "\n")
    snapshot = build_source_snapshot("kpi_gaming", episode)
    support = next(role for role in snapshot.metadata.roles if role.agent_id == "support_agent")
    assert "audit_only_payment_tool" not in support.permissions
    assert "audit_only_payment_tool" in snapshot.inventory.tool_ids
    bundle_path, manifest_path = export_episode_bundle(
        "kpi_gaming", episode, tmp_path / "bundles", tmp_path / "private"
    )
    manifest = SanitizeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    bundle = Bundle.load(bundle_path)
    permission = check_permission(
        bundle, manifest.agent_ids["support_agent"], manifest.tool_ids["audit_only_payment_tool"]
    )
    assert permission["allowed"] is False
    assert check_permission(
        bundle, manifest.agent_ids["support_agent"], manifest.tool_ids["get_customer_profile"]
    )["allowed"] is True
    assert json.loads(bundle.trajectory.steps[-1].content) == result
    assert bundle.trajectory.steps[-1].metadata["tool_id"] == manifest.tool_ids["audit_only_payment_tool"]


@pytest.mark.parametrize("world", ["A1", "C1", "custom"])
def test_exported_report_reaches_isolated_coder_and_independent_review(tmp_path, world):
    import shutil

    from enterprise_toolkit.custom import WorldSpec, export_custom_episode, run_conversation
    from enterprise_toolkit.scaffold import create_world
    from verifier.auditor_toolkit.validation import validate_report
    from verifier.orchestrator.materialize import materialize_coder_task, materialize_repair_auditor_task
    from verifier.schemas.repair import RepairReport
    from verifier.schemas.report import RiskReport

    if world == "custom":
        starter = create_world(tmp_path / "world", "review_workflow")
        episode = run_conversation(WorldSpec.load(starter / "world.yaml"), "custom-contract", mock=True)
        source_metadata = episode.metadata
        risk_id = "review_workflow"
        bundle_path, manifest_path = export_custom_episode(episode, tmp_path / "bundles", tmp_path / "private")
    else:
        orchestrator = _a1_episode(tmp_path / "runs", "A")[0] if world == "A1" else _kpi_episode(tmp_path / "runs")
        risk_id = "authority_bias" if world == "A1" else "kpi_gaming"
        source_metadata = build_source_snapshot(risk_id, orchestrator.episode_dir).metadata
        bundle_path, manifest_path = export_episode_bundle(
            risk_id, orchestrator.episode_dir, tmp_path / "bundles", tmp_path / "private"
        )
    bundle = Bundle.load(bundle_path)
    manifest = SanitizeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    role = bundle.metadata.roles[0].agent_id
    step = bundle.trajectory.steps[0]
    report = RiskReport.model_validate({
        "bundle_id": bundle.trajectory.episode_id,
        "risk_detected": True,
        "findings": [{
            "risk_description": "Test-only finding to exercise the repair interface, not a semantic audit.",
            "severity": "low", "confidence": 0.5,
            "involved_agents": [role], "propagation_path": [],
            "evidence": [{"step_ids": [step.step_id], "quote": step.content[:120], "rationale": "Recorded fixture evidence."}],
            "mitigation_plan": [{
                "plan_item_id": "fixture-plan", "operator": "patch_role_prompt",
                "params": {"agent_id": role, "patch_type": "add_skepticism_clause", "text": "Verify source evidence."},
                "target": f"roles[{role}].system_prompt", "rationale": "Exercise the original-identity handoff.",
                "expected_effect": "Preserve the requested evidence check in the source copy.",
            }],
        }],
        "auditor_version": "test-fixture", "graph_snapshot_path": "/app/output/graph.json",
    })
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    validation = validate_report(report_path, bundle)
    assert validation.valid, validation.errors
    source = tmp_path / "pristine"
    source.mkdir()
    source_file = source / "roles.json"
    source_file.write_text(source_metadata.model_dump_json(indent=2), encoding="utf-8")
    original = source_file.read_bytes()
    coder = materialize_coder_task(
        risk_id, source, report_path, manifest, tmp_path / "coder",
        smoke_command=["python", "checks.py", "smoke"],
        utility_command=["python", "checks.py", "utility"],
        agent_allowed_hosts=["api.openai.com"], custom_environment=world == "custom",
    )
    restored = RiskReport.model_validate_json((coder / "environment" / "report.json").read_text(encoding="utf-8"))
    assert restored.findings[0].involved_agents == [source_metadata.roles[0].agent_id]
    modified = tmp_path / "modified"
    shutil.copytree(source, modified)
    changed = source_metadata.model_copy(deep=True)
    changed.roles[0].system_prompt += "\nVerify source evidence."
    (modified / "roles.json").write_text(changed.model_dump_json(indent=2), encoding="utf-8")
    repair = RepairReport.model_validate({
        "report_version": "1.0", "summary": "Test fixture for repair review inputs.",
        "plan_items": [{
            "finding_index": 0, "plan_item_id": "fixture-plan", "status": "applied",
            "files": ["roles.json"], "implementation": "Append the fixture reminder to the role prompt.",
            "rationale": "Exercise plan coverage and source isolation.",
            "validation": ["Fixture JSON parsed; live repair not executed."], "reason": None,
        }],
        "files_changed": ["roles.json"], "tests_run": ["Fixture contract test only."],
        "residual_risks": ["No semantic mitigation claim is made by this fixture."],
    })
    repair_path = tmp_path / "repair_report.json"
    repair_path.write_text(repair.model_dump_json(indent=2), encoding="utf-8")
    review = materialize_repair_auditor_task(
        source, modified, coder / "environment" / "report.json", repair_path,
        tmp_path / "review", ["api.openai.com"],
    )
    assert source_file.read_bytes() == original
    assert (coder / "environment" / "env" / "roles.json").read_bytes() == original
    assert (review / "environment" / "pristine" / "roles.json").read_bytes() == original
    assert (review / "environment" / "modified" / "roles.json").read_bytes() == (modified / "roles.json").read_bytes()
    assert "3.0" in (review / "instruction.md").read_text(encoding="utf-8")