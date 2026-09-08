from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterprise_toolkit.cli import main


def test_list_exposes_exact_release_scope(capsys):
    assert main(["list", "--json"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert {world["paper_id"] for world in catalog["worlds"]} == {
        "A1", "B1", "C1", "D1", "F1"
    }
    assert catalog["verifier"]["profile"] == "v3-topology"


def test_info_distinguishes_a1_study_from_smoke(capsys):
    assert main(["info", "a1"]) == 0
    world = json.loads(capsys.readouterr().out)
    assert world["run_module"] == "run_authority"
    assert world["study_runners"][0]["run_module"] == "run_authority_title_effect"


def test_info_accepts_risk_id(capsys):
    assert main(["info", "semantic_drift"]) == 0
    assert json.loads(capsys.readouterr().out)["paper_id"] == "B1"


@pytest.mark.parametrize("identifier", ["A2", "B2", "missing"])
def test_info_rejects_unreleased_worlds(identifier, capsys):
    with pytest.raises(SystemExit) as error:
        main(["info", identifier])
    assert error.value.code == 2
    assert "Unknown world" in capsys.readouterr().err


def test_init_run_and_discovery_audit(tmp_path, capsys):
    from enterprise_toolkit.custom import WorldEpisode, WorldSpec
    from verifier.auditor_toolkit.bundle import Bundle

    world = tmp_path / "world"
    episode = tmp_path / "episode"
    output = tmp_path / "audit"
    assert main(["init", str(world), "--world-id", "invoice_review"]) == 0
    assert WorldSpec.load(world / "world.yaml").world_id == "invoice_review"
    assert main(["run-world", str(world / "world.yaml"), "--mock", "--out", str(episode)]) == 0
    assert WorldEpisode.load(episode).trajectory.outcome == {"execution_mode": "mock"}
    capsys.readouterr()
    assert main([
        "audit-world", str(episode), "--out", str(output), "--scope", str(world / "scope.md")
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["discovery_only"] is True
    assert result["semantic_audit_executed"] is False
    task = Path(result["auditor_task"])
    assert json.loads((task / "tests" / "ground_truth.json").read_text()) is None
    assert (task / "tests" / "manifest.json").is_file()
    assert not list((task / "environment").rglob("manifest.json"))
    assert not list((task / "environment").rglob("ground_truth.json"))
    assert "ENV VERIFIER_GRAPH_PROFILE=v3-topology" in (task / "environment" / "Dockerfile").read_text()
    assert "fixed taxonomy" in (task / "instruction.md").read_text()
    assert len(Bundle.load(Path(result["bundle"])).trajectory.steps) == 4


def test_demo_does_not_claim_audit_or_mitigation(tmp_path, capsys):
    output = tmp_path / "demo"
    assert main(["demo", "--out", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["execution_mode"] == "mock"
    assert result["semantic_audit_executed"] is False
    assert result["mitigation_executed"] is False
    assert not list(output.rglob("report.json"))
    assert json.loads((output / "demo.json").read_text()) == result
    with pytest.raises(SystemExit) as error:
        main(["demo", "--out", str(output)])
    assert error.value.code == 2


@pytest.mark.parametrize("world_id", ["a2", "b2", "../escape"])
def test_init_rejects_invalid_id_before_writing(tmp_path, world_id):
    output = tmp_path / "world"
    with pytest.raises(SystemExit) as error:
        main(["init", str(output), "--world-id", world_id])
    assert error.value.code == 2
    assert not output.exists()


def test_init_never_overwrites_a_directory(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("user work")
    with pytest.raises(SystemExit):
        main(["init", str(tmp_path)])
    assert marker.read_text() == "user work"
    assert not (tmp_path / "world.yaml").exists()


def test_run_requires_explicit_model_or_mock_mode(tmp_path, capsys):
    world = tmp_path / "world"
    main(["init", str(world)])
    with pytest.raises(SystemExit) as error:
        main(["run-world", str(world / "world.yaml"), "--out", str(tmp_path / "episode")])
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        main([
            "run-world", str(world / "world.yaml"), "--provider", "openai",
            "--out", str(tmp_path / "episode"),
        ])
    assert error.value.code == 2
    assert "--model is required" in capsys.readouterr().err
    assert not (tmp_path / "episode").exists()


def test_config_copies_original_bytes_without_overwriting(tmp_path):
    from enterprise_toolkit.resources import resource_path

    output = tmp_path / "study.yaml"
    assert main(["config", "A1", "--out", str(output)]) == 0
    original = resource_path("configs/authority_title_effect_realistic_power_abcd_n3.yaml")
    assert output.read_bytes() == original.read_bytes()
    with pytest.raises(SystemExit):
        main(["config", "B1", "--out", str(output)])
    assert output.read_bytes() == original.read_bytes()


@pytest.mark.parametrize("world_id,risk_id,smoke", [
    ("A1", "authority_bias", "configs/authority_smoke.yaml"),
    ("b1", "semantic_drift", "configs/drift_smoke.yaml"),
    ("C1", "kpi_gaming", "configs/smoke.yaml"),
    ("D1", "d1", "configs/d1_smoke.yaml"),
    ("F1", "f1", "configs/f1_smoke.yaml"),
])
def test_unified_run_uses_packaged_smoke_and_propagates_exit(
    tmp_path, monkeypatch, world_id, risk_id, smoke
):
    import run_risk
    from enterprise_toolkit.resources import resource_path

    calls = []

    def record_run(identifier, **kwargs):
        calls.append((identifier, kwargs))
        return 7

    monkeypatch.setattr(run_risk, "run_environment", record_run)
    assert main(["run", world_id, "--out", str(tmp_path)]) == 7
    assert calls == [(risk_id, {"config": resource_path(smoke), "runs_dir": tmp_path})]


def test_unified_run_preserves_explicit_config(tmp_path, monkeypatch):
    import run_risk

    config = tmp_path / "custom.yaml"
    calls = []
    monkeypatch.setattr(run_risk, "run_environment", lambda identifier, **kwargs: calls.append(kwargs))
    assert main(["run", "C1", "--config", str(config), "--out", str(tmp_path)]) == 0
    assert calls[0]["config"] == config


@pytest.mark.parametrize("world_id", ["A2", "B2"])
def test_unified_run_rejects_excluded_worlds(tmp_path, world_id):
    with pytest.raises(SystemExit) as error:
        main(["run", world_id, "--out", str(tmp_path)])
    assert error.value.code == 2


@pytest.mark.parametrize("world_id,module", [
    ("A1", "run_authority_title_effect"), ("B1", "run_drift"),
    ("C1", "run"), ("D1", "run_d1"), ("F1", "run_f1_paper_study"),
])
def test_study_defaults_to_preview_with_correct_runner(tmp_path, monkeypatch, capsys, world_id, module):
    from enterprise_toolkit import commands

    def reject_execution(*args, **kwargs):
        raise AssertionError("A preview must not start a process")

    monkeypatch.setattr(commands.subprocess, "run", reject_execution)
    assert main(["study", world_id, "--out", str(tmp_path / "runs")]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["command"][2] == module
    assert preview["execution_requested"] is False
    assert not (tmp_path / "runs").exists()
    if world_id == "F1":
        assert "--calibration-config" in preview["command"]
        assert preview["command"][-2:] == ["--max-workers", "1"]


def test_study_execution_propagates_exit_code(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from enterprise_toolkit import commands

    calls = []

    def record_run(command, *, check):
        calls.append(command)
        assert check is False
        return SimpleNamespace(returncode=5)

    monkeypatch.setattr(commands.subprocess, "run", record_run)
    assert main(["study", "A1", "--mock", "--execute", "--out", str(tmp_path)]) == 5
    assert "--dry-run" in calls[0]


@pytest.mark.parametrize("flags", [["--mock"], ["--index", "0"], ["--max-workers", "0"]])
def test_study_rejects_invalid_options(tmp_path, flags):
    with pytest.raises(SystemExit) as error:
        main(["study", "B1", "--out", str(tmp_path), *flags])
    assert error.value.code == 2


def test_verify_help_uses_unified_program_name(capsys):
    with pytest.raises(SystemExit) as error:
        main(["verify", "coder-task", "--help"])
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "eair verify coder-task" in output
    assert "--checks" in output


def test_verify_preserves_arguments_and_exit(monkeypatch):
    import verifier.cli

    calls = []

    def record_main(argv, *, prog):
        calls.append((argv, prog))
        return 9

    monkeypatch.setattr(verifier.cli, "main", record_main)
    assert main(["verify", "run", "task", "--profile", "custom"]) == 9
    assert calls == [(["run", "task", "--profile", "custom"], "eair verify")]


def test_docs_can_open_or_export_without_a_server(tmp_path, monkeypatch, capsys):
    from enterprise_toolkit import commands

    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html><title>Toolkit docs</title>", encoding="utf-8")
    monkeypatch.setattr(commands, "SITE_ROOT", site)
    opened = []
    monkeypatch.setattr(commands.webbrowser, "open", lambda uri: opened.append(uri) or True)
    assert main(["docs", "--no-open"]) == 0
    assert not opened
    exported = tmp_path / "published"
    assert main(["docs", "--export", str(exported)]) == 0
    assert opened == [(exported / "index.html").resolve().as_uri()]
    assert (exported / "index.html").read_bytes() == (site / "index.html").read_bytes()
    with pytest.raises(SystemExit):
        main(["docs", "--export", str(exported), "--no-open"])


def test_verify_coder_reads_checks_file(tmp_path, monkeypatch):
    import verifier.cli
    from verifier.schemas.sanitize_manifest import SanitizeManifest

    main(["demo", "--out", str(tmp_path / "demo")])
    manifest = next((tmp_path / "demo" / "private-manifests").glob("*.json"))
    checks = tmp_path / "checks.json"
    commands = {"smoke_command": ["python", "checks.py", "smoke"], "utility_command": ["python", "checks.py", "utility"]}
    checks.write_text(json.dumps(commands), encoding="utf-8")
    calls = []

    def record_task(*args, **kwargs):
        calls.append(args)
        return tmp_path / "coder"

    monkeypatch.setattr(verifier.cli, "materialize_coder_task", record_task)
    assert main([
        "verify", "coder-task", "purchase_review", str(tmp_path / "source"),
        str(tmp_path / "report.json"), str(manifest), str(tmp_path / "coder"),
        "--custom-environment", "--checks", str(checks),
    ]) == 0
    assert isinstance(calls[0][3], SanitizeManifest)
    assert calls[0][5:7] == (commands["smoke_command"], commands["utility_command"])


@pytest.mark.parametrize("value", ["[]", '[""]', '["python", " "]', '"python"', '["python", 3]'])
def test_verifier_checks_reject_empty_or_nonstring_arguments(value):
    from verifier.cli import _command_list

    with pytest.raises(ValueError, match="nonempty JSON string array"):
        _command_list(value)


def test_unified_verifier_reports_actionable_errors(monkeypatch, capsys):
    import verifier.cli

    def unavailable(*args, **kwargs):
        raise RuntimeError("Harbor CLI is not installed")

    monkeypatch.setattr(verifier.cli, "main", unavailable)
    with pytest.raises(SystemExit) as error:
        main(["verify", "run", "task"])
    assert error.value.code == 2
    assert "Harbor CLI is not installed" in capsys.readouterr().err


def test_primary_cli_brand_and_compatibility_alias(capsys):
    import tomllib

    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["scripts"]["eair"] == project["scripts"]["enterprise-toolkit"] == "enterprise_toolkit.cli:main"
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert "usage: eair " in help_text
    assert "Enterprise Agent Risk (EAIR)" in help_text