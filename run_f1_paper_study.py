"""Run the canonical ten-model F1 N=3 study with resumable model isolation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from enterprise_toolkit.resources import resource_path
from f1_provenance_paradox.ground_truth import DELEGATES
from llm.judge_policy import JUDGE_MODEL

ROOT = Path(__file__).resolve().parent
DEFAULT_MAIN_CONFIG = resource_path("configs/f1_paper_priority_10models_n3.yaml")
DEFAULT_CALIBRATION_CONFIG = resource_path(
    "configs/f1_paper_priority_10models_n3_calibration.yaml"
)
DEFAULT_RUN_ROOT = Path("runs") / "f1_paper_priority_10models_n3"
MAX_ATTEMPTS = 3

_status_lock = threading.Lock()
_statuses: dict[str, dict[str, Any]] = {}


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", model.split("/")[-1])


def _load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return rows if isinstance(rows, list) else []


def _completed(run_dir: Path) -> int:
    return len(_load_results(run_dir / "results.json"))


def _write_status(run_root: Path, calibration_target: int, main_target: int) -> None:
    lines = [
        "# F1 10-Model N=3 Run Status",
        "",
        f"Last updated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Run root: `{run_root}`",
        "",
        "| Model | Phase | Calibration | Main | Detail |",
        "|---|---|---:|---:|---|",
    ]
    for model, status in _statuses.items():
        detail = str(status.get("detail", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {model} | {status.get('phase', 'queued')} | "
            f"{status.get('calibration', 0)}/{calibration_target} | "
            f"{status.get('main', 0)}/{main_target} | {detail} |"
        )
    lines.extend([
        "",
        "## Design",
        "",
        f"- Solo calibration: {len(_statuses)} models x {len(DELEGATES)} delegates x "
        f"{calibration_target // len(DELEGATES)} reviews.",
        f"- Main matrix: {len(_statuses)} models x {main_target // 3} conditions x 3 episodes.",
        f"- Offline judge: `{JUDGE_MODEL}`.",
        "- Model directories and result files are resumable after interruption.",
    ])
    status_path = run_root / "RUN_STATUS.md"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = status_path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(status_path)


def _update(
    model: str,
    run_root: Path,
    calibration_target: int,
    main_target: int,
    **changes: Any,
) -> None:
    with _status_lock:
        _statuses[model].update(changes)
        _write_status(run_root, calibration_target, main_target)


def _run_logged(command: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n[{datetime.now().astimezone().isoformat()}] $ {' '.join(command)}\n"
        )
        handle.flush()
        result = subprocess.run(
            command,
            cwd=log_path.parent,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
        handle.write(
            f"[{datetime.now().astimezone().isoformat()}] exit={result.returncode}\n"
        )
        return result.returncode


def _write_model_config(
    source: dict[str, Any],
    model: str,
    path: Path,
    solo_capability_path: Path | None = None,
) -> None:
    config = dict(source)
    config.pop("models", None)
    config["model"] = model
    if solo_capability_path is not None:
        config["solo_capability_path"] = str(solo_capability_path.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _run_until_target(
    command: list[str],
    run_dir: Path,
    target: int,
    log_path: Path,
) -> bool:
    for _ in range(MAX_ATTEMPTS):
        if _completed(run_dir) >= target:
            return True
        _run_logged(command, log_path)
    return _completed(run_dir) >= target


def _run_calibration_model(
    model: str,
    config: dict[str, Any],
    run_root: Path,
    calibration_target: int,
    main_target: int,
) -> bool:
    slug = _slug(model)
    run_dir = run_root / "calibration" / slug
    config_path = run_root / "generated_configs" / f"calibration_{slug}.yaml"
    log_path = run_dir / "pipeline.log"
    _write_model_config(config, model, config_path)
    _update(
        model,
        run_root,
        calibration_target,
        main_target,
        phase="calibrating",
        calibration=_completed(run_dir),
        detail="Running solo reviews",
    )
    complete = _run_until_target(
        [
            sys.executable,
            "-u",
            str(ROOT / "run_f1_calibration.py"),
            "--config",
            str(config_path),
            "--out",
            str(run_dir),
        ],
        run_dir,
        calibration_target,
        log_path,
    )
    completed = _completed(run_dir)
    _update(
        model,
        run_root,
        calibration_target,
        main_target,
        phase="calibrated" if complete else "calibration_failed",
        calibration=completed,
        detail="Solo calibration complete" if complete else "See calibration pipeline.log",
    )
    return complete


def _merge_calibration(
    models: list[str],
    run_root: Path,
    calibration_target: int,
) -> Path:
    merged: dict[str, Any] = {"n_reviews": 0, "models": {}}
    for model in models:
        run_dir = run_root / "calibration" / _slug(model)
        summary_path = run_dir / "calibration_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        model_payload = summary.get("models", {}).get(model)
        if not model_payload or _completed(run_dir) != calibration_target:
            raise RuntimeError(f"Incomplete calibration for {model}")
        merged["models"][model] = model_payload
        merged["n_reviews"] += calibration_target
    path = run_root / "calibration_summary.json"
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return path


def _run_main_model(
    model: str,
    config: dict[str, Any],
    calibration_path: Path,
    run_root: Path,
    calibration_target: int,
    main_target: int,
) -> bool:
    slug = _slug(model)
    run_dir = run_root / "main" / slug
    config_path = run_root / "generated_configs" / f"main_{slug}.yaml"
    log_path = run_dir / "pipeline.log"
    _write_model_config(config, model, config_path, calibration_path)
    _update(
        model,
        run_root,
        calibration_target,
        main_target,
        phase="simulating",
        main=_completed(run_dir),
        detail="Running nine-condition main matrix",
    )
    simulated = _run_until_target(
        [
            sys.executable,
            "-u",
            str(ROOT / "run_f1.py"),
            "--config",
            str(config_path),
            "--out",
            str(run_dir),
        ],
        run_dir,
        main_target,
        log_path,
    )
    completed = _completed(run_dir)
    if not simulated:
        _update(
            model,
            run_root,
            calibration_target,
            main_target,
            phase="simulation_failed",
            main=completed,
            detail="See main pipeline.log",
        )
        return False
    _update(
        model,
        run_root,
        calibration_target,
        main_target,
        phase="judging",
        main=completed,
        detail=f"Judging with {JUDGE_MODEL}",
    )
    judge_exit = 0
    judged = len(_load_results(run_dir / "judge_results.json"))
    for _ in range(MAX_ATTEMPTS):
        if judged >= main_target:
            break
        judge_exit = _run_logged(
            [sys.executable, "-u", str(ROOT / "judge_f1.py"), str(run_dir)],
            log_path,
        )
        judged = len(_load_results(run_dir / "judge_results.json"))
    if judge_exit != 0 or judged != main_target:
        _update(
            model,
            run_root,
            calibration_target,
            main_target,
            phase="judge_failed",
            main=completed,
            detail=f"Judged {judged}/{main_target}; see pipeline.log",
        )
        return False
    _update(
        model,
        run_root,
        calibration_target,
        main_target,
        phase="analyzing",
        main=completed,
        detail="Writing per-model summary",
    )
    analyze_exit = _run_logged(
        [sys.executable, "-u", str(ROOT / "analyze_f1.py"), str(run_dir)],
        log_path,
    )
    complete = analyze_exit == 0
    _update(
        model,
        run_root,
        calibration_target,
        main_target,
        phase="complete" if complete else "analysis_failed",
        main=completed,
        detail="Pipeline complete" if complete else "See pipeline.log",
    )
    return complete


def _write_combined_outputs(models: list[str], run_root: Path) -> None:
    results: list[dict[str, Any]] = []
    judge_results: list[dict[str, Any]] = []
    for model in models:
        run_dir = run_root / "main" / _slug(model)
        results.extend(_load_results(run_dir / "results.json"))
        judge_results.extend(_load_results(run_dir / "judge_results.json"))
    (run_root / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    (run_root / "judge_results.json").write_text(
        json.dumps(judge_results, indent=2), encoding="utf-8"
    )
    exit_code = _run_logged(
        [sys.executable, "-u", str(ROOT / "analyze_f1.py"), str(run_root)],
        run_root / "pipeline.log",
    )
    if exit_code != 0:
        raise RuntimeError("Combined F1 analysis failed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the F1 ten-model N=3 study")
    parser.add_argument("--main-config", type=Path, default=DEFAULT_MAIN_CONFIG)
    parser.add_argument(
        "--calibration-config", type=Path, default=DEFAULT_CALIBRATION_CONFIG
    )
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--max-workers", type=int, default=3)
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("max-workers must be at least 1")

    main_config = _load_yaml(args.main_config)
    calibration_config = _load_yaml(args.calibration_config)
    models = list(main_config.get("models", []))
    if models != list(calibration_config.get("models", [])) or not models:
        parser.error("Main and calibration configs must contain the same models")
    episodes_per_agent = int(calibration_config.get("episodes_per_agent", 3))
    episodes_per_condition = int(main_config.get("episodes_per_condition", 3))
    condition_count = len(main_config.get("conditions", []))
    calibration_target = len(DELEGATES) * episodes_per_agent
    main_target = condition_count * episodes_per_condition
    run_root = args.run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    for rank, model in enumerate(models, start=1):
        _statuses[model] = {
            "rank": rank,
            "phase": "queued",
            "calibration": _completed(run_root / "calibration" / _slug(model)),
            "main": _completed(run_root / "main" / _slug(model)),
            "detail": "Waiting to start",
        }
    with _status_lock:
        _write_status(run_root, calibration_target, main_target)

    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(models))) as pool:
        futures = {
            pool.submit(
                _run_calibration_model,
                model,
                calibration_config,
                run_root,
                calibration_target,
                main_target,
            ): model
            for model in models
        }
        calibration_outcomes = {
            futures[future]: future.result() for future in as_completed(futures)
        }
    if not all(calibration_outcomes.values()):
        raise SystemExit("One or more F1 calibration cells remain incomplete")

    calibration_path = _merge_calibration(models, run_root, calibration_target)
    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(models))) as pool:
        futures = {
            pool.submit(
                _run_main_model,
                model,
                main_config,
                calibration_path,
                run_root,
                calibration_target,
                main_target,
            ): model
            for model in models
        }
        main_outcomes = {
            futures[future]: future.result() for future in as_completed(futures)
        }
    if not all(main_outcomes.values()):
        raise SystemExit("One or more F1 main-model pipelines remain incomplete")
    _write_combined_outputs(models, run_root)


if __name__ == "__main__":
    main()