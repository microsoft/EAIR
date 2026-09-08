"""Unified command adapters for existing study and verifier implementations."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from enterprise_toolkit.resources import resource_path


SITE_ROOT = Path(__file__).resolve().parent / "site"


def run_study(args: argparse.Namespace, world: dict) -> int:
    configs = world["recommended_configs"]
    if not 1 <= args.index <= len(configs):
        raise ValueError(f"study index must be between 1 and {len(configs)}")
    config = args.config if args.config is not None else resource_path(configs[args.index - 1])
    if not config.is_file():
        raise FileNotFoundError(f"study config does not exist: {config}")
    if args.mock and world["paper_id"] != "A1":
        raise ValueError("--mock is supported for the A1 study only; use 'run WORLD' for other offline smoke runs")
    if args.calibration_config is not None and world["paper_id"] != "F1":
        raise ValueError("--calibration-config is for the F1 study only")
    if args.max_workers < 1:
        raise ValueError("--max-workers must be at least 1")
    if args.max_workers != 1 and world["paper_id"] != "F1":
        raise ValueError("--max-workers is for the F1 study only")
    if world["paper_id"] == "A1":
        command = [sys.executable, "-m", "run_authority_title_effect", "--config", str(config.resolve()), "--out", str(args.out.resolve())]
        if args.mock:
            command.append("--dry-run")
    elif world["paper_id"] == "F1":
        calibration = args.calibration_config if args.calibration_config is not None else resource_path(world["supplemental_configs"][0])
        if not calibration.is_file():
            raise FileNotFoundError(f"calibration config does not exist: {calibration}")
        command = [
            sys.executable, "-m", "run_f1_paper_study",
            "--main-config", str(config.resolve()), "--calibration-config", str(calibration.resolve()),
            "--run-root", str(args.out.resolve()), "--max-workers", str(args.max_workers),
        ]
    else:
        command = [sys.executable, "-m", world["run_module"], "--config", str(config.resolve()), "--runs-dir", str(args.out.resolve())]
    print(json.dumps({
        "world": world["paper_id"], "command": command,
        "execution_requested": args.execute,
        "notice": "Study presets may incur model charges. Preview does not run an experiment. See 'info' for cohort and runner limitations.",
    }, indent=2), flush=True)
    return subprocess.run(command, check=False).returncode if args.execute else 0


def build_graph(args: argparse.Namespace) -> int:
    from verifier.auditor_toolkit.cli import build_graph_main

    return build_graph_main([str(args.bundle), "--output", str(args.out), "--profile", args.profile])


def check_report(args: argparse.Namespace) -> int:
    from verifier.auditor_toolkit.cli import validate_report_main

    return validate_report_main([str(args.report), "--bundle", str(args.bundle)])


def open_docs(args: argparse.Namespace) -> int:
    entry = SITE_ROOT / "index.html"
    if not entry.is_file():
        raise FileNotFoundError("This installation is missing the documentation website; reinstall the current wheel")
    if args.export is not None:
        shutil.copytree(SITE_ROOT, args.export)
        entry = args.export / "index.html"
    print(entry.resolve())
    if not args.no_open:
        if not webbrowser.open(entry.resolve().as_uri()):
            print("A browser could not be opened. Open the printed HTML path manually.", file=sys.stderr)
    return 0