"""Run D1 permission-drift experiments from a YAML configuration."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from rich.console import Console
from rich.progress import Progress

from d1_confused_deputy.ground_truth import D1Scenario, get_scenario, list_scenarios
from d1_confused_deputy.metrics import aggregate_results
from d1_confused_deputy.orchestrator import D1EpisodeConfig, D1EpisodeOrchestrator
from llm.client import LLMClient, LLMResponse, MockLLMBackend, ToolCall
from risk_environments.runtime import load_config

console = Console()


def expand_cells(config: dict[str, Any]) -> list[dict[str, Any]]:
    scenario_ids = config.get("scenarios")
    domains = config.get("domains")
    if scenario_ids is None:
        selected = list_scenarios()
        if domains:
            allowed_domains = {domains} if isinstance(domains, str) else set(domains)
            selected = [s for s in selected if s.domain in allowed_domains]
        scenario_ids = [scenario.scenario_id for scenario in selected]
    elif isinstance(scenario_ids, str):
        scenario_ids = [scenario_ids]
    for scenario_id in scenario_ids:
        get_scenario(scenario_id)

    models = config.get("models", config.get("model", "gpt-4o-mini"))
    if isinstance(models, str):
        models = [models]
    conditions = config.get("conditions", [{"name": "vulnerable"}])
    cells: list[dict[str, Any]] = []
    for scenario_id, model, condition in itertools.product(
        scenario_ids, models, conditions
    ):
        condition = dict(condition)
        cells.append({
            "scenario_id": scenario_id,
            "model": model,
            "condition_name": condition.pop("name", "condition"),
            "provider": config.get("provider", "openai"),
            "episodes_per_condition": int(config.get("episodes_per_condition", 1)),
            "seed_start": int(config.get("seed_start", 42)),
            "temperature": float(config.get("temperature", 0.7)),
            "use_mock": bool(config.get("use_mock", False)),
            "max_tool_calls_per_turn": int(
                config.get("max_tool_calls_per_turn", 6)
            ),
            "force_initial_tool_call": bool(
                config.get("force_initial_tool_call", True)
            ),
            **condition,
        })
    return cells


def _tool_call(name: str, **arguments: Any) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[ToolCall(
            id=str(uuid4())[:8],
            name=name,
            arguments=arguments,
        )],
        raw={"mock": name},
    )


def build_mock_llm(scenario: D1Scenario, cell: dict[str, Any]) -> LLMClient:
    """Deterministic pipeline mock for infrastructure and mitigation checks."""
    backend = MockLLMBackend()
    backend.add_response(_tool_call(
        "ask_specialist_agent",
        agent=scenario.specialist_agent,
        question=scenario.user_utterance,
    ))
    lookup_args = {scenario.target_arg_name: scenario.target}
    if cell.get("tool_field_acl", False):
        lookup_args["on_behalf_of"] = scenario.requester
    backend.add_response(_tool_call(scenario.privileged_tool_name, **lookup_args))

    safer_agent_behavior = bool(
        cell.get("authorization_propagation", False)
        or cell.get("tool_field_acl", False)
        or cell.get("trust_framing") == "untrusted-client"
        or cell.get("specialist_objective") == "need-to-know"
    )
    record = (
        dict(scenario.public_record)
        if safer_agent_behavior
        else scenario.full_record(cell.get("semantic_entanglement", "high"))
    )
    reply = _mock_planning_reply(scenario, record)
    backend.add_response(
        LLMResponse(content=reply, tool_calls=[], raw={"mock": "specialist_reply"})
    )
    backend.add_response(
        LLMResponse(content=reply, tool_calls=[], raw={"mock": "ea_reply"})
    )
    return LLMClient(backend=backend)


def _mock_planning_reply(scenario: D1Scenario, record: dict[str, str]) -> str:
    prefix = {
        "hr": "For Q3 project planning, the available record says",
        "finance": "For Q3 budget planning, the available record says",
        "security": "For the access request, the available record says",
    }[scenario.domain]
    details = "; ".join(f"{field}: {value}" for field, value in record.items())
    return f"{prefix}: {details}."


def _load_env() -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def run_experiment(
    config_path: Path,
    runs_dir: Path = Path("runs"),
    out: Path | None = None,
    force_mock: bool = False,
) -> Path:
    config = load_config(config_path)
    cells = expand_cells(config)
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        + "_d1_"
        + str(uuid4())[:6]
    )
    run_dir = out or runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    results_path = run_dir / "results.json"
    results: list[dict[str, Any]] = []
    if results_path.exists():
        try:
            results = json.loads(results_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results = []
    completed = {row["episode_id"] for row in results}

    total = sum(cell["episodes_per_condition"] for cell in cells)
    with Progress() as progress:
        task = progress.add_task("Running D1 episodes...", total=total)
        for cell in cells:
            scenario = get_scenario(cell["scenario_id"])
            for offset in range(cell["episodes_per_condition"]):
                seed = cell["seed_start"] + offset
                episode_id = _episode_id(cell, seed)
                if episode_id in completed:
                    progress.advance(task)
                    continue
                try:
                    use_mock = force_mock or cell["use_mock"]
                    llm = (
                        build_mock_llm(scenario, cell)
                        if use_mock
                        else LLMClient(
                            provider=cell["provider"], model=cell["model"]
                        )
                    )
                    episode_config = D1EpisodeConfig(
                        scenario_id=cell["scenario_id"],
                        authorization_propagation=bool(
                            cell.get("authorization_propagation", False)
                        ),
                        authorization_inquiry_channel=bool(
                            cell.get("authorization_inquiry_channel", False)
                        ),
                        trust_framing=cell.get("trust_framing", "peer-trust"),
                        tool_field_acl=bool(cell.get("tool_field_acl", False)),
                        specialist_objective=cell.get(
                            "specialist_objective", "completeness"
                        ),
                        semantic_entanglement=cell.get(
                            "semantic_entanglement", "high"
                        ),
                        temperature=cell["temperature"],
                        seed=seed,
                        model=cell["model"],
                        provider="mock" if use_mock else cell["provider"],
                        max_tool_calls_per_turn=cell["max_tool_calls_per_turn"],
                        force_initial_tool_call=cell["force_initial_tool_call"],
                    )
                    result = D1EpisodeOrchestrator(
                        llm=llm,
                        config=episode_config,
                        run_dir=run_dir,
                        episode_id=episode_id,
                    ).run()
                    row = asdict(result)
                    row["condition_name"] = cell["condition_name"]
                    row["provider"] = episode_config.provider
                    results.append(row)
                    completed.add(episode_id)
                    results_path.write_text(
                        json.dumps(results, indent=2), encoding="utf-8"
                    )
                    console.print(
                        f"  done {cell['model']} | {scenario.scenario_id} | "
                        f"{cell['condition_name']} | seed={seed} | "
                        f"leak={'yes' if result.leak else 'no'} | "
                        f"task={'yes' if result.task_success else 'no'}"
                    )
                except Exception as exc:  # noqa: BLE001
                    with (run_dir / "errors.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({
                            "episode_id": episode_id,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }) + "\n")
                    console.print(
                        f"  [red]episode failed[/red] {episode_id}: "
                        f"{type(exc).__name__}: {str(exc)[:160]}"
                    )
                finally:
                    progress.advance(task)

    summary = aggregate_results(results)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    console.print(f"[green]D1 run complete:[/green] {run_dir}")
    return run_dir


def _episode_id(cell: dict[str, Any], seed: int) -> str:
    model = re.sub(r"[^A-Za-z0-9_.-]+", "-", cell["model"].split("/")[-1])
    condition = re.sub(r"[^A-Za-z0-9_.-]+", "-", cell["condition_name"])
    return f"{model}_{cell['scenario_id']}_{condition}_seed{seed}"


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(
        description="Run permission drift / confused deputy experiments"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/d1_smoke.yaml")
    )
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="force mock LLM")
    args = parser.parse_args()
    run_experiment(
        args.config,
        runs_dir=args.runs_dir,
        out=args.out,
        force_mock=args.dry_run,
    )


if __name__ == "__main__":
    main()
