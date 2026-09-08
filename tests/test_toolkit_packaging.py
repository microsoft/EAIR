from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_risk
from enterprise_toolkit import resources


ROOT = Path(__file__).resolve().parents[1]


def _project_metadata():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_release_declarations_include_real_study_code():
    import enterprise_toolkit

    metadata = _project_metadata()
    project = metadata["project"]
    settings = metadata["tool"]["setuptools"]
    modules = set(settings["py-modules"])
    packages = settings["packages"]["find"]
    assert project["version"] == "0.3.1"
    assert enterprise_toolkit.__version__ == project["version"] == resources.load_catalog()["release_version"]
    assert project["readme"] == "README.md"
    assert project["license"] == {"file": "LICENSE"}
    assert settings["license-files"] == ["LICENSE"]
    assert project["scripts"]["enterprise-toolkit"] == "enterprise_toolkit.cli:main"
    assert project["scripts"]["eair"] == project["scripts"]["enterprise-toolkit"]
    assert packages["namespaces"] is False
    assert settings["include-package-data"] is False
    assert {"authority_deference", "authority_title_effect", "enterprise_toolkit"} <= set(
        packages["include"]
    )
    assert not any("*" in package for package in packages["include"])
    assert not {"tacit_collusion", "aggregator_sway"} & set(packages["include"])
    assert {
        "run", "run_risk", "run_authority", "run_authority_title_effect",
        "run_drift", "run_d1", "run_f1", "run_f1_calibration", "run_f1_paper_study",
        "judge_authority", "judge_drift", "judge_d1", "judge_f1", "judge_kpi",
        "analyze_f1",
    } <= modules
    assert all((ROOT / f"{module}.py").is_file() for module in modules)


def test_live_dependencies_are_optional():
    project = _project_metadata()["project"]
    assert set(project["dependencies"]) == {
        "pydantic>=2.0", "pyyaml>=6.0", "networkx>=3.2", "rich>=13.0"
    }
    assert set(project["optional-dependencies"]["live"]) == {
        "openai>=1.0", "anthropic>=0.25", "azure-identity>=1.17"
    }
    assert {"pytest>=7.0", "build>=1.0"} <= set(project["optional-dependencies"]["dev"])
    assert "harbor" not in project["optional-dependencies"]


def test_harbor_template_allowlist_is_complete():
    patterns = _project_metadata()["tool"]["setuptools"]["package-data"]["verifier"]
    selected = {path for pattern in patterns for path in (ROOT / "verifier").glob(pattern)}
    required = {
        path
        for template in ("auditor_template", "coder_template", "repair_auditor_template")
        for path in (ROOT / "verifier" / "harbor_tasks" / template).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert selected == required
    assert len(required) == 20
    for template in ("auditor_template", "coder_template", "repair_auditor_template"):
        assert ROOT / "verifier" / "harbor_tasks" / template / "tests" / "grader.py" in selected
        assert ROOT / "verifier" / "harbor_tasks" / template / "tests" / "test.sh" in selected
        assert ROOT / "verifier" / "harbor_tasks" / template / "environment" / "Dockerfile" in selected


def test_source_inventory_is_exact_and_includes_backend():
    import _toolkit_build as backend

    selected = backend.source_files(ROOT)
    assert selected == tuple(sorted(set(selected)))
    assert "_toolkit_build.py" in selected
    assert "authority_title_effect/orchestrator.py" in selected
    assert "run_authority_title_effect.py" in selected
    assert "run_f1_calibration.py" in selected
    assert "run_f1_paper_study.py" in selected
    assert "analyze_f1.py" in selected
    assert "tools/build_paper_trajectory_manifest.py" not in selected
    assert "verifier/orchestrator/mast.py" not in selected
    assert "enterprise_toolkit/site/index.html" in selected
    assert "enterprise_toolkit/site/assets/workflow.png" in selected
    assert "enterprise_toolkit/site/assets/mark.png" not in selected
    assert "enterprise_toolkit/site/assets/manrope.woff2" in selected
    assert "enterprise_toolkit/site/assets/lucide-LICENSE.txt" in selected
    assert {path for path in selected if path.startswith("tests/")} == set(backend.SOURCE_TESTS)
    assert {path for path in selected if path.startswith("verifier/runs/")} == {
        backend.HISTORICAL_CONFIG
    }
    assert backend.selected_configs(ROOT) == resources.selected_config_paths()
    assert all(
        backend._allowed_path(path) or path == backend.HISTORICAL_CONFIG
        for path in selected
    )
    assert _project_metadata()["build-system"]["build-backend"] == "_toolkit_build"
    assert _project_metadata()["build-system"]["backend-path"] == ["."]


@pytest.mark.parametrize(
    "relative_path",
    [
        "tacit_collusion/__init__.py", "aggregator_sway/__init__.py",
        "tests/test_a2.py", "tests/test_b2.py", "verifier/runs/private.py",
        "enterprise_toolkit/private.py", "enterprise_toolkit/credentials.json",
        "enterprise_toolkit/__pycache__/resources.pyc", "llm/.env",
        "enterprise_toolkit/templates/secret.key", "analysis/results.json",
        "manifests/selection.json", "bundles/trajectory.json",
    ],
)
def test_release_policy_rejects_nonrelease_paths(relative_path):
    import _toolkit_build as backend

    assert not backend._allowed_path(relative_path)


def test_config_copy_is_deterministic_and_preserves_original_metadata(tmp_path):
    import _toolkit_build as backend

    selected = resources.selected_config_paths()
    originals = [ROOT / "enterprise_toolkit" / "catalog.json", *(ROOT / path for path in selected)]
    before = {
        path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in originals
    }
    first = backend.copy_selected_configs(ROOT, tmp_path / "first")
    stale = tmp_path / "first" / "enterprise_toolkit" / "assets" / "stale.json"
    stale.write_text("{}", encoding="utf-8")
    assert backend.copy_selected_configs(ROOT, tmp_path / "first") == first
    assert not stale.exists()
    second = backend.copy_selected_configs(ROOT, tmp_path / "second")
    for relative_path, first_path, second_path in zip(selected, first, second, strict=True):
        assert Path(first_path).read_bytes() == Path(second_path).read_bytes() == (ROOT / relative_path).read_bytes()
        assert Path(first_path).stat().st_mtime_ns == Path(second_path).stat().st_mtime_ns
    after = {
        path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in originals
    }
    assert before == after


def test_config_copy_cannot_write_to_source_package():
    import _toolkit_build as backend

    with pytest.raises(ValueError, match="source package"):
        backend.copy_selected_configs(ROOT, ROOT)


def test_staging_validates_readme_before_copying(tmp_path):
    import _toolkit_build as backend

    assert (ROOT / "README.md").is_file(), "A release must include its declared README"
    selected = backend.stage_sources(ROOT, tmp_path)
    assert {
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*") if path.is_file()
    } == set(selected)


def test_role_and_artifact_resources_are_selected():
    import _toolkit_build as backend

    selected = set(backend.source_files(ROOT))
    for package in ("agents", "authority_deference", "semantic_drift", "d1_confused_deputy"):
        roles = list((ROOT / package / "roles").glob("*.yaml"))
        assert roles
        assert all(path.relative_to(ROOT).as_posix() in selected for path in roles)
    artifacts = list((ROOT / "f1_provenance_paradox" / "artifacts").glob("*.md"))
    assert len(artifacts) == 7
    assert all(path.relative_to(ROOT).as_posix() in selected for path in artifacts)


def _offline_import_script(import_root):
    modules = _project_metadata()["tool"]["setuptools"]["py-modules"]
    return f"""
import importlib
import importlib.abc
import sys
from pathlib import Path

class NoLiveSDKs(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'openai', 'anthropic', 'azure', 'matplotlib', 'harbor'}}:
            raise ModuleNotFoundError('Live or analysis dependency imported: ' + fullname)
        return None

sys.meta_path.insert(0, NoLiveSDKs())
sys.path.insert(0, {str(import_root)!r})
for module_name in {modules!r}:
    module = importlib.import_module(module_name)
    assert Path(module.__file__).resolve().is_relative_to(Path({str(import_root)!r}).resolve())
from enterprise_toolkit.resources import resource_path, selected_config_paths
for relative_path in selected_config_paths():
    assert resource_path(relative_path).is_file()
"""


def test_runtime_modules_import_without_live_dependencies(tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", "-c", _offline_import_script(ROOT)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_a1_real_study_smoke_uses_packaged_config_bytes(tmp_path, monkeypatch):
    import yaml

    import _toolkit_build as backend
    import run_authority_title_effect as runner

    backend.copy_selected_configs(ROOT, tmp_path / "runtime")
    package_root = tmp_path / "runtime" / "enterprise_toolkit"
    (package_root / "catalog.json").write_bytes((ROOT / "enterprise_toolkit" / "catalog.json").read_bytes())
    monkeypatch.setattr(resources, "_PACKAGE_ROOT", package_root)
    monkeypatch.chdir(tmp_path)

    def reject_live_client(*args, **kwargs):
        raise AssertionError("Packaging smoke must not create a live client")

    monkeypatch.setattr(runner, "_make_real_llm", reject_live_client)
    config_path = resources.resource_path("configs/authority_title_effect_realistic_power_abcd_n3.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    original = config_path.read_bytes()
    output = runner.run_experiment(config_path, SimpleNamespace(
        conditions="A", roles=config["roles"][0], seeds=1,
        model="mock", provider="mock", reporter_model="mock", reporter_provider="mock",
        dry_run=True, out=tmp_path / "a1-study",
    ))
    result = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(result) == 1
    executed = yaml.safe_load((output / "config.yaml").read_text(encoding="utf-8"))
    assert executed["protocol"] == "realistic_organizational_power_v4"
    assert executed["use_mock"] is True
    assert (output / result[0]["episode_id"] / "artifacts.json").is_file()
    assert config_path.read_bytes() == original


def test_wheel_sdist_round_trip_and_installed_resources(tmp_path):
    pytest.importorskip("build")
    pytest.importorskip("setuptools")
    pytest.importorskip("wheel")
    import _toolkit_build as backend

    original_files = [ROOT / "pyproject.toml", ROOT / "enterprise_toolkit" / "catalog.json"]
    original_files.extend((ROOT / "enterprise_microworld.egg-info").glob("*"))
    before = {path: path.read_bytes() for path in original_files if path.is_file()}
    dist = tmp_path / "dist"
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(dist)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(path.read_bytes() == content for path, content in before.items())
    sources = set(backend.source_files(ROOT))
    configs = set(backend.selected_configs(ROOT))
    expected_runtime = sources - set(backend.ROOT_FILES) - set(backend.SOURCE_DOCS) - set(backend.SOURCE_TESTS) - configs
    expected_runtime.update(f"enterprise_toolkit/assets/{path}" for path in configs)
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    installed = tmp_path / "site-packages"
    with zipfile.ZipFile(wheels[0]) as archive:
        members = {name for name in archive.namelist() if not name.endswith("/")}
        licenses = [name for name in members if name.endswith("/LICENSE") and name.split("/")[0].endswith(".dist-info")]
        assert len(licenses) == 1
        assert archive.read(licenses[0]) == (ROOT / "LICENSE").read_bytes()
        runtime = {name for name in members if not name.split("/")[0].endswith(".dist-info")}
        assert runtime == expected_runtime
        for path in configs:
            assert archive.read(f"enterprise_toolkit/assets/{path}") == (ROOT / path).read_bytes()
        assert archive.read("enterprise_toolkit/catalog.json") == (ROOT / "enterprise_toolkit" / "catalog.json").read_bytes()
        archive.extractall(installed)
    with tarfile.open(sdists[0]) as archive:
        files = [member for member in archive.getmembers() if member.isfile()]
        members = {member.name.split("/", 1)[1] for member in files}
        assert sources <= members
        extra = members - sources - {"PKG-INFO", "setup.cfg"}
        assert all(
            len(Path(path).parts) == 2
            and Path(path).parts[0].endswith(".egg-info")
            and Path(path).name in backend.EGG_INFO_FILES
            for path in extra
        )
        assert not any(member.issym() or member.islnk() for member in archive.getmembers())
    script = _offline_import_script(installed) + f"""
from enterprise_toolkit.cli import main
assert callable(main)
for relative_path in selected_config_paths():
    assert resource_path(relative_path).is_relative_to(Path({str(installed)!r}) / 'enterprise_toolkit' / 'assets')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], cwd=tmp_path,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_selected_resources_exist_and_catalog_reads_are_independent():
    catalog = resources.load_catalog()
    original = json.loads(json.dumps(catalog))
    selected = resources.selected_config_paths(catalog)
    assert selected == tuple(sorted(set(selected)))
    assert {world["paper_id"] for world in catalog["worlds"]} == {
        "A1", "B1", "C1", "D1", "F1"
    }
    assert catalog == original
    for relative_path in selected:
        assert resources.resource_path(relative_path).is_file()
    catalog["worlds"][0]["recommended_configs"].clear()
    assert resources.load_catalog() == original


@pytest.mark.parametrize(
    "relative_path",
    [
        "../pyproject.toml", "/configs/smoke.yaml", "C:/configs/smoke.yaml",
        "configs/../configs/smoke.yaml", "configs\\smoke.yaml",
        "configs//smoke.yaml", "configs/./smoke.yaml", "configs/smoke.yaml:secret",
        "", "configs/unselected.yaml", "verifier/runs/private.json",
    ],
)
def test_resource_traversal_and_unselected_paths_rejected(relative_path):
    with pytest.raises(ValueError):
        resources.resource_path(relative_path)


def test_installed_resources_never_fall_through_to_site_packages(tmp_path, monkeypatch):
    package_root = tmp_path / "site-packages" / "enterprise_toolkit"
    package_root.mkdir(parents=True)
    (package_root / "catalog.json").write_text(
        json.dumps(resources.load_catalog()), encoding="utf-8"
    )
    unrelated_config = package_root.parent / "configs" / "smoke.yaml"
    unrelated_config.parent.mkdir()
    unrelated_config.write_text("not_a_toolkit_resource: true\n", encoding="utf-8")
    monkeypatch.setattr(resources, "_PACKAGE_ROOT", package_root)
    (package_root.parent / "pyproject.toml").write_text(
        '[project]\nname = "enterprise-microworld"\n', encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError):
        resources.resource_path("configs/smoke.yaml")

    asset = package_root / "assets" / "configs" / "smoke.yaml"
    asset.parent.mkdir(parents=True)
    asset.write_text("mode: smoke\n", encoding="utf-8")
    assert resources.resource_path("configs/smoke.yaml") == asset.resolve()


def test_resource_symlink_escape_is_rejected(tmp_path, monkeypatch):
    package_root = tmp_path / "enterprise_toolkit"
    asset = package_root / "assets" / "configs" / "smoke.yaml"
    asset.parent.mkdir(parents=True)
    (package_root / "catalog.json").write_text(json.dumps(resources.load_catalog()), encoding="utf-8")
    outside = tmp_path / "outside.yaml"
    outside.write_text("private: true\n", encoding="utf-8")
    try:
        asset.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this platform")
    monkeypatch.setattr(resources, "_PACKAGE_ROOT", package_root)
    with pytest.raises(ValueError, match="symlink|escapes"):
        resources.resource_path("configs/smoke.yaml")


def test_default_run_config_uses_resources_outside_checkout(tmp_path, monkeypatch):
    calls = []

    def record_run(command, *, check):
        calls.append(command)
        assert check is False
        return SimpleNamespace(returncode=7)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_risk.subprocess, "run", record_run)
    assert run_risk.run_environment("authority_bias") == 7
    config = Path(calls[0][calls[0].index("--config") + 1])
    assert config == resources.resource_path("configs/authority_smoke.yaml")


def test_explicit_missing_run_config_is_not_replaced(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="explicit.yaml"):
        run_risk.run_environment("authority_bias", config=Path("explicit.yaml"))


def test_default_run_config_preserves_cwd_override(tmp_path, monkeypatch):
    config = tmp_path / "configs" / "authority_smoke.yaml"
    config.parent.mkdir()
    config.write_text("mode: custom\n", encoding="utf-8")
    calls = []

    def record_run(command, *, check):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_risk.subprocess, "run", record_run)
    assert run_risk.run_environment("authority_bias") == 0
    assert calls[0][calls[0].index("--config") + 1] == str(Path("configs/authority_smoke.yaml"))


def test_f1_study_defaults_use_packaged_configs_and_writable_run_root(tmp_path, monkeypatch):
    import run_f1_paper_study as study

    assert study.DEFAULT_MAIN_CONFIG == resources.resource_path("configs/f1_paper_priority_10models_n3.yaml")
    assert study.DEFAULT_CALIBRATION_CONFIG == resources.resource_path("configs/f1_paper_priority_10models_n3_calibration.yaml")
    assert not study.DEFAULT_RUN_ROOT.is_absolute()
    monkeypatch.setattr(study, "_statuses", {"mock": {"phase": "queued"}})
    study._write_status(tmp_path / "run", 9, 27)
    assert (tmp_path / "run" / "RUN_STATUS.md").is_file()
    assert "mock" in (tmp_path / "run" / "RUN_STATUS.md").read_text(encoding="utf-8")


def test_f1_study_subprocess_works_in_output_not_install_directory(tmp_path, monkeypatch):
    import run_f1_paper_study as study

    calls = []

    def record_run(command, **kwargs):
        calls.append((command, kwargs["cwd"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(study.subprocess, "run", record_run)
    log_path = tmp_path / "run" / "pipeline.log"
    assert study._run_logged(["python", "example.py"], log_path) == 0
    assert calls == [(["python", "example.py"], log_path.parent)]