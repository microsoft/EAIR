"""Run F1 solo capability calibration without routing incentives."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from rich.console import Console
from rich.progress import Progress

from f1_provenance_paradox.ground_truth import DELEGATES
from f1_provenance_paradox.metrics import score_landmines
from f1_provenance_paradox.orchestrator import F1EpisodeConfig, F1EpisodeOrchestrator
from llm.client import LLMClient
from run_f1 import _load_env, build_mock_solo_llm, load_config

console = Console()


def aggregate_calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for model in sorted({row["model"] for row in rows}):
        model_rows = [row for row in rows if row["model"] == model]
        delegates: dict[str, Any] = {}
        for delegate in DELEGATES:
            selected = [row for row in model_rows if row["delegate"] == delegate]
            delegates[delegate] = {}
            for landmine_id in ("L1", "L2", "L3"):
                scores = [float(row["landmines"][landmine_id]) for row in selected]
                delegates[delegate][landmine_id] = (
                    sum(score == 1.0 for score in scores) / len(scores)
                    if scores else 0.0
                )
                delegates[delegate][f"{landmine_id}_partial_rate"] = (
                    sum(score == 0.5 for score in scores) / len(scores)
                    if scores else 0.0
                )
                delegates[delegate][f"{landmine_id}_mean_score"] = (
                    sum(scores) / len(scores) if scores else 0.0
                )
            delegates[delegate]["n_reviews"] = len(selected)
        models[model] = {"delegates": delegates}
    return {"n_reviews": len(rows), "models": models}


def run_calibration(
    config_path: Path,
    runs_dir: Path = Path("runs"),
    out: Path | None = None,
    force_mock: bool = False,
) -> Path:
    config = load_config(config_path)
    models = config.get("models", config.get("model", "gpt-4o-mini"))
    if isinstance(models, str):
        models = [models]
    episodes_per_agent = int(config.get("episodes_per_agent", 20))
    seed_start = int(config.get("seed_start", 1000))
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        + "_f1_solo_"
        + str(uuid4())[:6]
    )
    run_dir = out or runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    results_path = run_dir / "results.json"
    rows = (
        json.loads(results_path.read_text(encoding="utf-8"))
        if results_path.exists()
        else []
    )
    rescored = False
    for row in rows:
        artifacts_path = run_dir / row["episode_id"] / "artifacts.json"
        if not artifacts_path.exists():
            continue
        artifacts = json.loads(artifacts_path.read_text(encoding="utf-8"))
        updated = score_landmines(artifacts.get("review", {}).get("report", ""))
        if row.get("landmines") != updated:
            row["landmines"] = updated
            rescored = True
    if rescored:
        results_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    completed = {row["episode_id"] for row in rows}
    total = len(models) * len(DELEGATES) * episodes_per_agent
    with Progress() as progress:
        task = progress.add_task("Running F1 solo reviews...", total=total)
        for model in models:
            for delegate in DELEGATES:
                for offset in range(episodes_per_agent):
                    seed = seed_start + offset
                    episode_id = f"{model.split('/')[-1]}_{delegate}_solo_seed{seed}"
                    if episode_id in completed:
                        progress.advance(task)
                        continue
                    use_mock = force_mock or bool(config.get("use_mock", False))
                    try:
                        llm = (
                            build_mock_solo_llm(delegate)
                            if use_mock
                            else LLMClient(
                                provider=config.get("provider", "openai"), model=model
                            )
                        )
                        episode_config = F1EpisodeConfig(
                            incentive=False,
                            sla_hours=72,
                            time_pressure=False,
                            cost_pressure=False,
                            temperature=float(config.get("temperature", 0.7)),
                            seed=seed,
                            model=model,
                            provider="mock" if use_mock else config.get("provider", "openai"),
                            max_tool_calls_per_turn=int(
                                config.get("max_tool_calls_per_turn", 8)
                            ),
                        )
                        result = F1EpisodeOrchestrator(
                            llm, episode_config, run_dir, episode_id=episode_id
                        ).run_solo(delegate)
                        rows.append(result)
                        completed.add(episode_id)
                        results_path.write_text(
                            json.dumps(rows, indent=2), encoding="utf-8"
                        )
                    except Exception as exc:  # noqa: BLE001
                        with (run_dir / "errors.jsonl").open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps({
                                "episode_id": episode_id,
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            }) + "\n")
                    finally:
                        progress.advance(task)
    summary = aggregate_calibration(rows)
    (run_dir / "calibration_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    console.print(f"[green]F1 solo calibration complete:[/green] {run_dir}")
    return run_dir


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Run F1 solo capability calibration")
    parser.add_argument(
        "--config", type=Path, default=Path("configs/f1_solo_calibration.yaml")
    )
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="force mock LLM")
    args = parser.parse_args()
    run_calibration(
        args.config,
        runs_dir=args.runs_dir,
        out=args.out,
        force_mock=args.dry_run,
    )


if __name__ == "__main__":
    main()