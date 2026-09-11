"""Run with a clean environment's Python after installing the release wheel."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


EXPORT_CHECK = """
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from enterprise_toolkit.cli import main
from verifier.auditor_toolkit.bundle import Bundle

risk_id, source_root, destination_root = sys.argv[1:]
destination = Path(destination_root)
episodes = list(Path(source_root).rglob('meta.json'))
assert episodes, 'No recorded episodes found'
for position, metadata_path in enumerate(episodes):
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(['verify', 'export', risk_id, str(metadata_path.parent),
                     '--bundles-root', str(destination / 'bundles'),
                     '--manifests-root', str(destination / 'private')]) == 0
    exported = json.loads(output.getvalue())
    bundle = Bundle.load(Path(exported['bundle']))
    assert bundle.trajectory.steps
    task = destination / 'tasks' / str(position)
    with redirect_stdout(io.StringIO()):
        assert main(['verify', 'auditor-task', exported['bundle'], '-', exported['manifest'],
                     str(task), '--discovery-only', '--profile', 'v3-topology']) == 0
    assert Bundle.load(task / 'environment' / 'bundle').trajectory == bundle.trajectory
    assert (task / 'tests' / 'manifest.json').is_file()
    assert not (task / 'environment' / 'bundle' / 'manifest.json').exists()
print(json.dumps({'episodes_exported': len(episodes), 'auditor_tasks_prepared': len(episodes),
                  'semantic_audit_executed': False}))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Check an installed toolkit without checkout imports")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    records = []
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    environment["PYTHONUTF8"] = "1"
    suffix = ".exe" if os.name == "nt" else ""
    scripts = Path(sys.executable).parent
    toolkit = str(scripts / f"eair{suffix}")
    legacy_toolkit = str(scripts / f"enterprise-toolkit{suffix}")
    risk_cli = str(scripts / f"enterprise-risk{suffix}")
    python = [sys.executable, "-I", "-X", "utf8"]
    success = False

    with TemporaryDirectory(prefix="enterprise-toolkit-installed-") as temporary:
        working = Path(temporary)

        def check(name: str, command: list[str]) -> str:
            result = subprocess.run(
                command, cwd=working, env=environment, capture_output=True,
                text=True, encoding="utf-8", errors="replace", check=False,
            )
            records.append({
                "check": name, "returncode": result.returncode,
                "stdout": result.stdout[-6000:], "stderr": result.stderr[-6000:],
            })
            print(f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
            result.check_returncode()
            return result.stdout

        try:
            check("isolated-runtime", [*python, "-c", "\n".join([
                "import importlib.metadata, importlib.util, json, sys, yaml",
                "from pathlib import Path",
                "import enterprise_toolkit",
                "from enterprise_toolkit.resources import load_catalog, resource_path, selected_config_paths",
                "assert importlib.metadata.version('enterprise-microworld') == '0.3.2'",
                "assert enterprise_toolkit.__version__ == '0.3.2'",
                "assert Path(enterprise_toolkit.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())",
                "assert all(importlib.util.find_spec(name) is None for name in ('openai', 'anthropic', 'azure', 'harbor'))",
                "assert len(selected_config_paths()) == 15",
                "assert all(resource_path(name).is_file() for name in selected_config_paths())",
                "assert all(yaml.safe_load(resource_path(world['smoke_config']).read_text(encoding='utf-8'))['use_mock'] is True for world in load_catalog()['worlds'])",
                "print(json.dumps({'version': '0.3.2', 'package': enterprise_toolkit.__file__, 'presets': 15}))",
            ])])
            check("console-version", [toolkit, "--version"])
            listing = json.loads(check("five-world-catalog", [toolkit, "list", "--json"]))
            assert {world["paper_id"] for world in listing["worlds"]} == {"A1", "B1", "C1", "D1", "F1"}
            assert json.loads(check("legacy-toolkit-alias", [legacy_toolkit, "list", "--json"])) == listing
            assert "Enterprise Agent Risk (EAIR)" in check("eair-help-identity", [toolkit, "--help"])
            demo = json.loads(check("custom-demo", [toolkit, "demo", "--out", str(working / "demo")]))
            assert demo["semantic_audit_executed"] is False
            assert demo["mitigation_executed"] is False
            check("topology-graph", [
                str(scripts / f"build-graph{suffix}"), demo["bundle"],
                "--profile", "v3-topology", "-o", str(working / "graph.json"),
            ])
            for risk_id in ("authority_bias", "semantic_drift", "kpi_gaming", "d1", "f1"):
                check(f"smoke-{risk_id}", [
                    toolkit, "run", risk_id, "--out", str(working / risk_id),
                ])
                results = list((working / risk_id).rglob("results.json"))
                assert results, f"No results produced for {risk_id}"
                for result_path in results:
                    rows = json.loads(result_path.read_text(encoding="utf-8"))
                    assert isinstance(rows, list) and rows, f"Empty or invalid results for {risk_id}"
                    assert not any(row.get("error") for row in rows), f"Execution errors in {risk_id} results"
                check(f"export-and-audit-task-{risk_id}", [
                    *python, "-c", EXPORT_CHECK, risk_id, str(working / risk_id),
                    str(working / "audit-exports" / risk_id),
                ])
            study_config = working / "a1-study.yaml"
            check("a1-config-export", [toolkit, "config", "A1", "--out", str(study_config)])
            check("a1-title-effect-study", [
                *python, "-m", "run_authority_title_effect", "--config", str(study_config),
                "--conditions", "A", "--seeds", "1", "--dry-run",
                "--out", str(working / "a1-title-effect"),
            ])
            check("a1-title-effect-export-and-audit", [
                *python, "-c", EXPORT_CHECK, "authority_bias", str(working / "a1-title-effect"),
                str(working / "audit-exports" / "a1-title-effect"),
            ])
            factorial_config = working / "a1-factorial.yaml"
            check("a1-factorial-config", [toolkit, "config", "A1", "--index", "2", "--out", str(factorial_config)])
            check("a1-factorial-study", [
                *python, "-m", "run_authority_title_effect", "--config", str(factorial_config),
                "--conditions", "E", "--seeds", "1", "--dry-run",
                "--out", str(working / "a1-factorial"),
            ])
            check("a1-factorial-export-and-audit", [
                *python, "-c", EXPORT_CHECK, "authority_bias", str(working / "a1-factorial"),
                str(working / "audit-exports" / "a1-factorial"),
            ])
            check("f1-calibration-study-entry", [*python, "-m", "run_f1_paper_study", "--help"])
            check("verifier-entry", [str(scripts / f"enterprise-verifier{suffix}"), "--help"])
            check("unified-verifier-entry", [toolkit, "verify", "--help"])
            check("module-entry", [*python, "-m", "enterprise_toolkit", "--help"])
            check("legacy-risk-alias", [risk_cli, "--list"])
            preview = json.loads(check("unified-study-preview", [toolkit, "study", "F1", "--out", str(working / "study-preview")]))
            assert preview["execution_requested"] is False
            assert preview["command"][2] == "run_f1_paper_study"
            assert not (working / "study-preview").exists()
            check("offline-docs-export", [toolkit, "docs", "--export", str(working / "docs"), "--no-open"])
            assert (working / "docs" / "index.html").is_file()
            assert (working / "docs" / "assets" / "workflow.png").is_file()
            assert (working / "docs" / "assets" / "manrope.woff2").is_file()
            assert not (working / "docs" / "assets" / "mark.png").exists()
            html = (working / "docs" / "index.html").read_text(encoding="utf-8")
            assert "Enterprise Agent Risk (EAIR)" in html
            assert 'class="brand-symbol"' not in html and 'rel="icon"' not in html
            check("unified-topology-graph", [toolkit, "graph", demo["bundle"], "--out", str(working / "unified-graph.json")])
            success = True
        except (AssertionError, OSError, subprocess.CalledProcessError) as error:
            print(f"Installed-wheel validation failed: {error}", file=sys.stderr)
            if records and records[-1]["returncode"]:
                print(records[-1]["stderr"], file=sys.stderr)
        finally:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({
                "success": success, "python": sys.version,
                "interpreter": sys.executable,
                "scope": "installed-wheel-offline-smoke",
                "semantic_audit_executed": False, "mitigation_executed": False,
                "checks": records,
            }, indent=2) + "\n", encoding="utf-8")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())