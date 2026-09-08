"""Offline Judge phase for an Authority Deference Bias run.

Run this AFTER run_authority.py completes. Writes judge_result.json into every
episode directory and merges the judge output into results.json.

Usage:
    python judge_authority.py runs/<run_id>
    python judge_authority.py runs/<run_id> --use-mock   # plumbing test only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from llm.client import LLMClient, LLMResponse
from llm.judge_policy import add_judge_arguments, create_judge_client
from authority_deference.judge import judge_episode
from authority_deference.schemas import DOWNSTREAM_AGENTS

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
    """Deterministic mock judge (plumbing only): calls everything 'internal' /
    'challenges', no vendor blame. NOT a real scoring."""

    class _AlwaysInternal:
        def chat(self, messages, tools, temperature, tool_choice=None, response_format=None):
            per_agent = {
                a: {
                    "attribution": "internal",
                    "vendor_causal_status": "vendor_downstream_only",
                    "deference": "challenges_with_evidence",
                    "contains_vendor_blame": False,
                    "cited_decisive_ordering": False,
                    "dissent_style": "explicit_correction",
                    "evidence": "mock",
                }
                for a in DOWNSTREAM_AGENTS
            }
            return LLMResponse(content=json.dumps({
                "final_report": {
                    "root_cause_attribution": "internal",
                    "vendor_causal_status": "vendor_downstream_only",
                    "evidence": "mock",
                },
                "per_agent": per_agent,
                "urgency_inheritance": {"any_output_states_ceo_request_as_fact": False, "evidence": ""},
            }), raw={})

    return LLMClient(backend=_AlwaysInternal())


def judge_run(run_dir: Path, llm: LLMClient) -> list:
    episode_dirs = sorted(
        p for p in run_dir.iterdir() if p.is_dir() and (p / "artifacts.json").exists()
    )
    results_path = run_dir / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else []
    results_by_id = {r["episode_id"]: r for r in results}

    judged = []
    with Progress() as progress:
        task = progress.add_task("Judging episodes...", total=len(episode_dirs))
        for ep_dir in episode_dirs:
            judge_result = judge_episode(ep_dir, llm)
            row = results_by_id.get(ep_dir.name, {"episode_id": ep_dir.name})
            row["condition"] = judge_result.get("condition", row.get("condition"))
            row["judge_result"] = judge_result
            judged.append(row)
            progress.advance(task)

    results_path.write_text(json.dumps(judged, indent=2), encoding="utf-8")
    return judged


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Judge a completed Authority Deference run")
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
        console.print(f"[yellow]Warning:[/yellow] {n_parse_errors} episodes had judge JSON parse errors (defaulted to safe/mixed).")


if __name__ == "__main__":
    main()
