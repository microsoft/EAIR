"""Offline Judge phase for a Semantic Drift run.

Run this AFTER run_drift.py completes (spec section 2: the Judge layer runs
only once every episode has finished, and its output never feeds back into
the simulation). Writes judge_result.json into every episode directory and
an updated results.json with the judge fields merged in.

Usage:
    python judge_drift.py runs/<run_id> --provider trapi --model gpt-5.6-sol_2026-07-09
    python judge_drift.py runs/<run_id> --use-mock   # for testing the plumbing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from llm.client import LLMClient, LLMResponse, MockLLMBackend
from llm.judge_policy import add_judge_arguments, create_judge_client
from semantic_drift.judge import judge_episode

console = Console()


def _load_env() -> None:
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def _mock_judge_llm() -> LLMClient:
    """Deterministic mock judge for smoke-testing the pipeline (not for real
    scoring — always calls everything preserved / not drifted)."""
    backend = MockLLMBackend()

    class _AlwaysPreserved:
        def chat(self, messages, tools, temperature, tool_choice=None, response_format=None):
            return LLMResponse(content=json.dumps({
                "artifact_scores": {},
                "run_level": {
                    "absence_represented": True,
                    "conflict_occurred": False,
                    "merge_direction": "not_applicable",
                    "customer_commitment_made": False,
                    "terminal_drift": False,
                    "self_healed": False,
                    "self_healed_stage": None,
                },
            }), raw={})

    return LLMClient(backend=_AlwaysPreserved())


def judge_run(run_dir: Path, llm: LLMClient) -> list[dict]:
    episode_dirs = sorted(
        p for p in run_dir.iterdir() if p.is_dir() and (p / "artifacts.json").exists()
    )
    results_path = run_dir / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else []
    results_by_id = {r["episode_id"]: r for r in results}

    judged: list[dict] = []
    with Progress() as progress:
        task = progress.add_task("Judging episodes...", total=len(episode_dirs))
        for ep_dir in episode_dirs:
            judge_result = judge_episode(ep_dir, llm)
            row = results_by_id.get(ep_dir.name, {"episode_id": ep_dir.name})
            row["judge_result"] = judge_result
            judged.append(row)
            progress.advance(task)

    results_path.write_text(json.dumps(judged, indent=2), encoding="utf-8")
    return judged


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Judge a completed Semantic Drift run")
    parser.add_argument("run_dir", type=Path)
    add_judge_arguments(parser)
    parser.add_argument("--use-mock", action="store_true")
    args = parser.parse_args()

    if not args.run_dir.exists():
        console.print(f"[red]No such run dir:[/red] {args.run_dir}")
        sys.exit(1)

    llm = _mock_judge_llm() if args.use_mock else create_judge_client()
    judged = judge_run(args.run_dir, llm)
    n_parse_errors = sum(1 for r in judged if r.get("judge_result", {}).get("parse_error"))
    console.print(f"[green]Judged {len(judged)} episodes[/green] in {args.run_dir}")
    if n_parse_errors:
        console.print(f"[yellow]Warning:[/yellow] {n_parse_errors} episodes had judge JSON parse errors (defaulted to safe/no-drift).")


if __name__ == "__main__":
    main()
