"""Run the project-standard offline judge over completed F1 episodes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress

from f1_provenance_paradox.judge import judge_episode
from llm.client import LLMClient, LLMResponse
from llm.judge_policy import JUDGE_MODEL, JUDGE_PROVIDER, add_judge_arguments, create_judge_client
from run_f1 import _load_env

console = Console()


def _mock_judge_llm() -> LLMClient:
    class _MockJudge:
        def chat(
            self,
            messages: list[dict[str, Any]],
            tools: Any,
            temperature: float,
            tool_choice: Any = None,
            response_format: Any = None,
        ) -> LLMResponse:
            return LLMResponse(content=json.dumps({
                "landmines": {
                    landmine_id: {
                        "score": 0,
                        "evidence_quote": "",
                        "rationale": "mock plumbing score",
                    }
                    for landmine_id in ("L1", "L2", "L3")
                },
                "summary_l3_risk_signal": {
                    "value": False,
                    "evidence_quote": "",
                    "rationale": "mock",
                },
                "provenance_retained": {
                    "value": False,
                    "evidence_quote": "",
                    "rationale": "mock",
                },
                "competitive_bid_revision": {
                    "applicable": False,
                    "score": 0,
                    "before_quote": "",
                    "after_quote": "",
                    "rationale": "mock",
                },
                "summary": "Mock plumbing result.",
            }), raw={"mock": True})

    return LLMClient(backend=_MockJudge())


def judge_run(
    run_dir: Path,
    llm: LLMClient,
    force: bool = False,
) -> list[dict[str, Any]]:
    episode_dirs = []
    for path in sorted(run_dir.iterdir()):
        artifacts_path = path / "artifacts.json"
        if not path.is_dir() or not artifacts_path.exists():
            continue
        episode_dirs.append(path)
    results_path = run_dir / "judge_results.json"
    existing = (
        json.loads(results_path.read_text(encoding="utf-8"))
        if results_path.exists()
        else []
    )
    results = {row["episode_id"]: row for row in existing}
    pending = [
        path for path in episode_dirs
        if force
        or path.name not in results
        or results[path.name].get("judge_result", {}).get("parse_error")
    ]
    with Progress() as progress:
        task = progress.add_task(
            "Judging F1 episodes...",
            total=len(episode_dirs),
            completed=len(episode_dirs) - len(pending),
        )
        for episode_dir in pending:
            try:
                results[episode_dir.name] = {
                    "episode_id": episode_dir.name,
                    "judge_result": judge_episode(episode_dir, llm),
                }
                results_path.write_text(
                    json.dumps([results[key] for key in sorted(results)], indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                with (run_dir / "judge_errors.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "episode_id": episode_dir.name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }) + "\n")
            finally:
                progress.advance(task)
    ordered = [results[key] for key in sorted(results)]
    valid = [row for row in ordered if not row["judge_result"].get("parse_error")]
    summary = {
        "judge_provider": JUDGE_PROVIDER,
        "judge_model": JUDGE_MODEL,
        "rubric_version": "f1-provenance-v1",
        "n_episode_artifacts": len(ordered),
        "n_valid_judgments": len(valid),
        "n_parse_errors": len(ordered) - len(valid),
        "semantic_risk_triggers": sum(
            bool(row["judge_result"]["semantic_verifier"]["risk_triggered"])
            for row in valid
        ),
    }
    (run_dir / "judge_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return ordered


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Judge a completed F1 run")
    parser.add_argument("run_dir", type=Path)
    add_judge_arguments(parser)
    parser.add_argument("--use-mock", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not args.run_dir.exists():
        console.print(f"[red]No such run dir:[/red] {args.run_dir}")
        sys.exit(1)
    llm = _mock_judge_llm() if args.use_mock else create_judge_client()
    judged = judge_run(args.run_dir, llm, force=args.force)
    parse_errors = sum(bool(row["judge_result"].get("parse_error")) for row in judged)
    console.print(
        f"[green]Judged {len(judged)} F1 episodes[/green] in {args.run_dir}; "
        f"parse_errors={parse_errors}"
    )


if __name__ == "__main__":
    main()