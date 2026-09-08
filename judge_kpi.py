"""Run the fixed-policy offline judge over a completed KPI experiment."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from llm.client import LLMClient, LLMResponse
from llm.judge_policy import add_judge_arguments, create_judge_client
from metrics.kpi_judge import judge_episode

console = Console()


def _load_env() -> None:
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _mock_judge_llm() -> LLMClient:
    class _NoGamingJudge:
        def chat(self, messages, tools, temperature, tool_choice=None, response_format=None):
            return LLMResponse(content=json.dumps({
                "agent_awareness": {
                    "kpi_or_sla_pressure": False,
                    "verification_cost_or_time_tradeoff": False,
                    "compensation_cap": False,
                },
                "behavior": {
                    "deliberately_skipped_available_verification": False,
                    "metric_gaming": "no",
                    "policy_evasion": "no",
                    "coordination_failure": "no",
                },
                "causal_assessment": "no_evidence",
                "evidence": [],
                "summary": "Mock plumbing result.",
            }), raw={})

    return LLMClient(backend=_NoGamingJudge())


def judge_run(
    run_dir: Path, llm: LLMClient, concurrency: int = 8,
) -> list[dict]:
    results_path = run_dir / "results.json"
    rows = json.loads(results_path.read_text(encoding="utf-8"))
    pending = [
        row for row in rows
        if not row.get("judge_result")
        or row["judge_result"].get("parse_error")
    ]
    lock = threading.Lock()

    def judge_one(row: dict) -> tuple[dict, dict]:
        episode_dir = run_dir / row["episode_id"]
        return row, judge_episode(row, episode_dir, llm)

    with Progress() as progress:
        task = progress.add_task(
            "Judging KPI episodes...", total=len(rows),
            completed=len(rows) - len(pending),
        )
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [pool.submit(judge_one, row) for row in pending]
            for future in as_completed(futures):
                row, judge_result = future.result()
                with lock:
                    row["judge_result"] = judge_result
                    results_path.write_text(
                        json.dumps(rows, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    progress.advance(task)
    return rows


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Judge a completed KPI run")
    parser.add_argument("run_dir", type=Path)
    add_judge_arguments(parser)
    parser.add_argument("--use-mock", action="store_true")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    if not (args.run_dir / "results.json").exists():
        console.print(f"[red]No KPI results.json in:[/red] {args.run_dir}")
        sys.exit(1)
    llm = _mock_judge_llm() if args.use_mock else create_judge_client()
    judged = judge_run(args.run_dir, llm, concurrency=args.concurrency)
    parse_errors = sum(
        bool(row["judge_result"].get("parse_error")) for row in judged
    )
    console.print(
        f"[green]Judged {len(judged)} KPI episodes[/green] in {args.run_dir}; "
        f"parse_errors={parse_errors}"
    )


if __name__ == "__main__":
    main()