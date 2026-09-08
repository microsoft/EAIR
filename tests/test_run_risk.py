"""Tests for the unified confirmed-risk CLI."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import run_risk


def test_run_environment_dispatches_to_existing_runner() -> None:
    completed = Mock(returncode=0)

    with patch("run_risk.subprocess.run", return_value=completed) as run:
        return_code = run_risk.run_environment(
            "semantic_drift",
            config=Path("configs/drift_smoke.yaml"),
            runs_dir=Path("custom-runs"),
        )

    assert return_code == 0
    run.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "run_drift",
            "--config",
            "configs\\drift_smoke.yaml" if sys.platform == "win32" else "configs/drift_smoke.yaml",
            "--runs-dir",
            "custom-runs",
        ],
        check=False,
    )


def test_list_shows_only_confirmed_risks(capsys) -> None:
    assert run_risk.main(["--list"]) == 0

    output = capsys.readouterr().out
    assert "kpi_gaming" in output
    assert "authority_bias" in output
    assert "semantic_drift" in output
    assert "d1" in output
    assert "f1" in output
    assert "a2" not in output
    assert "b2" not in output