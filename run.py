"""Run experiments from YAML config."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml
from rich.console import Console
from rich.progress import Progress

from llm.client import LLMClient, LLMResponse, ToolCall
from orchestrator.episode import EpisodeConfig, EpisodeOrchestrator
from risk_environments.runtime import load_config
from world.enterprise import EnterpriseWorld

console = Console()

CUSTOMER_PROVIDER = "trapi"
CUSTOMER_MODEL = "gpt-5.6-sol_2026-07-09"


def expand_conditions(config: dict) -> list[dict]:
    """Expand grid of experimental conditions."""
    pressures = config.get("kpi_pressure", ["none"])
    visibilities = config.get("visibility", ["on_demand"])
    modes = config.get("mode", ["multi_agent"])
    routings = config.get("routing", ["front_door"])
    models = config.get("model", ["gpt-4o-mini"])
    persona_types = config.get("persona_type", [None])
    verification_costs = config.get("verification_cost_minutes", [3.0])
    kpi_dashboards = config.get("kpi_dashboard", [True])
    initial_compensations = config.get("initial_compensation", [0.0])
    if isinstance(pressures, str):
        pressures = [pressures]
    if isinstance(visibilities, str):
        visibilities = [visibilities]
    if isinstance(modes, str):
        modes = [modes]
    if isinstance(routings, str):
        routings = [routings]
    if isinstance(models, str):
        models = [models]
    if isinstance(persona_types, str):
        persona_types = [persona_types]
    if not isinstance(verification_costs, list):
        verification_costs = [verification_costs]
    if not isinstance(kpi_dashboards, list):
        kpi_dashboards = [kpi_dashboards]
    if not isinstance(initial_compensations, list):
        initial_compensations = [initial_compensations]

    conditions = []
    for (
        kp, vis, mode, routing, model, persona_type, verification_cost,
        kpi_dashboard, initial_compensation,
    ) in itertools.product(
        pressures, visibilities, modes, routings, models, persona_types,
        verification_costs, kpi_dashboards,
        initial_compensations,
    ):
        if persona_type:
            persona_mix = {persona_type: 1.0}
        else:
            persona_mix = config.get("persona_mix", {
                "benign": 0.2, "persistent": 0.5, "strategic": 0.3,
            })
        conditions.append({
            "kpi_pressure": kp,
            "visibility": vis,
            "mode": mode,
            "routing": routing,
            "episodes_per_condition": config.get("episodes_per_condition", 20),
            "max_handoff_rounds": config.get("max_handoff_rounds", 2),
            "temperature": config.get("temperature", 0.7),
            "global_policy_in_prompt": config.get("global_policy_in_prompt", False),
            "seed": config.get("seed", 42),
            "customer_id": config.get("customer_id"),
            "episode_seed": config.get("episode_seed"),
            "model": model,
            "provider": config.get("provider", "openai"),
            "persona_mix": persona_mix,
            "persona_type": persona_type,
            "use_mock": config.get("use_mock", False),
            "max_customer_exchanges": config.get("max_customer_exchanges", 10),
            "max_approval_rounds": config.get("max_approval_rounds", 2),
            "verification_cost_minutes": float(verification_cost),
            "customer_reply_delay_minutes": float(
                config.get("customer_reply_delay_minutes", 2.0)
            ),
            "kpi_dashboard": bool(kpi_dashboard),
            "initial_compensation": float(initial_compensation),
            "contact_plan": config.get("contact_plan", "standard"),
            "sla_targets": config.get("sla_targets", {
                "outage": 8.0,
                "retention": 10.0,
                "billing_dispute": 6.0,
                "goodwill": 8.0,
            }),
        })
    return conditions


def build_mock_llm() -> LLMClient:
    """Build a mock LLM that drives a minimal happy-path episode."""
    from llm.client import MockLLMBackend

    backend = MockLLMBackend()

    def contact_turn() -> list[LLMResponse]:
        return [
            LLMResponse(
                tool_calls=[ToolCall(
                    id="tc1",
                    name="get_customer_profile",
                    arguments={"customer_id": "C-001"},
                )],
                content=None,
                raw={},
            ),
            LLMResponse(
                tool_calls=[ToolCall(
                    id="tc2",
                    name="issue_credit",
                    arguments={
                        "customer_id": "C-001",
                        "amount": 15.0,
                        "reason_code": "outage",
                    },
                )],
                content=None,
                raw={},
            ),
            LLMResponse(
                tool_calls=[ToolCall(
                    id="tc3",
                    name="reply_to_customer",
                    arguments={"content": "I've issued a $15 credit for the outage."},
                )],
                content=None,
                raw={},
            ),
            LLMResponse(
                tool_calls=[ToolCall(
                    id="tc4",
                    name="close_ticket",
                    arguments={"resolution_note": "Issued credit for outage."},
                )],
                content=None,
                raw={},
            ),
            LLMResponse(content="Case resolved.", raw={}),
        ]

    for _ in range(5):
        for resp in contact_turn():
            backend.add_response(resp)
    for _ in range(100):
        backend.add_response(LLMResponse(
            content="Thank you for contacting us. How can I help?",
            raw={},
        ))

    return LLMClient(backend=backend)


def run_experiment(config_path: Path, runs_dir: Path | None = None) -> Path:
    """Run all conditions and episodes; return run directory."""
    config = load_config(config_path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:6]
    run_dir = (runs_dir or Path("runs")) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with (run_dir / "config.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(config, f)

    conditions = expand_conditions(config)
    concurrency = int(config.get("concurrency", 1))
    all_results: list[dict] = []
    results_path = run_dir / "results.json"
    lock = threading.Lock()

    # One shared LLM client per model for real runs: avoids re-authenticating
    # per episode and is safe to call from multiple threads. Mock runs need a
    # fresh scripted backend per episode, so those are built in the worker.
    shared_llms: dict[str, LLMClient] = {}
    for c in conditions:
        if not c.get("use_mock") and c["model"] not in shared_llms:
            shared_llms[c["model"]] = LLMClient(
                provider=c.get("provider", "openai"), model=c["model"],
            )
    customer_llm = (
        LLMClient(provider=CUSTOMER_PROVIDER, model=CUSTOMER_MODEL)
        if any(not condition.get("use_mock") for condition in conditions)
        else None
    )

    # Precompute every episode job deterministically so seeded customer
    # selection is identical regardless of execution order or concurrency.
    jobs: list[dict] = []
    for cond in conditions:
        rng = random.Random(cond["seed"])
        customer_ids = list(EnterpriseWorld(seed=cond["seed"]).customers.keys())
        for ep_i in range(cond["episodes_per_condition"]):
            customer_id = (
                cond["customer_id"]
                or ("C-001" if cond.get("use_mock") else rng.choice(customer_ids))
            )
            episode_seed = (
                cond["episode_seed"]
                if cond["episode_seed"] is not None
                else cond["seed"] + ep_i
            )
            jobs.append({
                "cond": cond,
                "ep_i": ep_i,
                "customer_id": customer_id,
                "episode_seed": episode_seed,
            })

    def _run_one(job: dict) -> dict:
        cond = job["cond"]
        ep_i = job["ep_i"]
        customer_id = job["customer_id"]
        world = EnterpriseWorld(seed=cond["seed"])
        llm = build_mock_llm() if cond.get("use_mock") else shared_llms[cond["model"]]
        episode_customer_llm = llm if cond.get("use_mock") else customer_llm
        ep_config = EpisodeConfig(
            kpi_pressure=cond["kpi_pressure"],
            visibility=cond["visibility"],
            mode=cond["mode"],
            routing=cond.get("routing", "front_door"),
            max_handoff_rounds=cond["max_handoff_rounds"],
            max_customer_exchanges=cond.get("max_customer_exchanges", 10),
            max_approval_rounds=cond.get("max_approval_rounds", 2),
            temperature=cond["temperature"],
            global_policy_in_prompt=cond["global_policy_in_prompt"],
            seed=job["episode_seed"],
            persona_mix=cond["persona_mix"],
            persona_type=cond.get("persona_type"),
            verification_cost_minutes=cond["verification_cost_minutes"],
            customer_reply_delay_minutes=cond["customer_reply_delay_minutes"],
            sla_targets=cond["sla_targets"],
            kpi_dashboard=cond["kpi_dashboard"],
            initial_compensation=cond.get("initial_compensation", 0.0),
            contact_plan=cond.get("contact_plan", "standard"),
        )
        orch = EpisodeOrchestrator(
            world=world,
            llm=llm,
            customer_llm=episode_customer_llm,
            config=ep_config,
            run_dir=run_dir,
        )
        result = orch.run(customer_id)
        return {
            "condition": {
                "kpi_pressure": cond["kpi_pressure"],
                "visibility": cond["visibility"],
                "mode": cond["mode"],
                "routing": cond.get("routing", "front_door"),
                "model": cond["model"],
                "provider": cond.get("provider", "openai"),
                "customer_model": (
                    cond["model"] if cond.get("use_mock") else CUSTOMER_MODEL
                ),
                "customer_provider": (
                    cond.get("provider", "mock")
                    if cond.get("use_mock")
                    else CUSTOMER_PROVIDER
                ),
                "persona_type": result.persona_type,
                "verification_cost_minutes": cond["verification_cost_minutes"],
                "customer_reply_delay_minutes": cond["customer_reply_delay_minutes"],
                "sla_targets": cond["sla_targets"],
                "kpi_dashboard": cond["kpi_dashboard"],
                "initial_compensation": cond.get("initial_compensation", 0.0),
                "contact_plan": cond.get("contact_plan", "standard"),
            },
            "episode_id": result.episode_id,
            "episode_seed": job["episode_seed"],
            "customer_id": result.customer_id,
            "persona_type": result.persona_type,
            "total_comp": result.total_comp,
            "final_total_comp": result.total_comp,
            "initial_compensation": cond.get("initial_compensation", 0.0),
            "episode_issued_comp": round(
                result.total_comp - cond.get("initial_compensation", 0.0), 2,
            ),
            "cap_exceeded": result.cap_exceeded,
            "structured_violation": result.structured_violation,
            "emergent_violation": result.emergent_violation,
            "n_paying_agents": result.n_paying_agents,
            "n_reason_mismatch": result.n_reason_mismatch,
            "reason_code_mismatch_rate": result.reason_code_mismatch_rate,
            "mean_csat": result.mean_csat,
            "csat_scores": result.csat_scores,
            "per_agent_csat": result.per_agent_csat,
            "csat_log": result.csat_log,
            "history_check_rate": result.history_check_rate,
            "handoff_disclosure_rate": result.handoff_disclosure_rate,
            "handoff_inquiry_rate": result.handoff_inquiry_rate,
            "invoice_adjustment_attempts": result.invoice_adjustment_attempts,
            "verified_invoice_adjustment_attempts": result.verified_invoice_adjustment_attempts,
            "unverified_invoice_adjustment_attempts": result.unverified_invoice_adjustment_attempts,
            "successful_invoice_adjustments": result.successful_invoice_adjustments,
            "rejected_invoice_adjustment_attempts": result.rejected_invoice_adjustment_attempts,
            "justified_invoice_refunds": result.justified_invoice_refunds,
            "unjustified_invoice_refunds": result.unjustified_invoice_refunds,
            "unknown_ground_truth_refunds": result.unknown_ground_truth_refunds,
            "verified_justified_refunds": result.verified_justified_refunds,
            "unverified_justified_refunds": result.unverified_justified_refunds,
            "verified_unjustified_refunds": result.verified_unjustified_refunds,
            "unverified_unjustified_refunds": result.unverified_unjustified_refunds,
            "invoice_verification_rate": result.invoice_verification_rate,
            "invoice_refund_violation_rate": result.invoice_refund_violation_rate,
            "crossing_agent": result.crossing_agent,
            "crossing_tool": result.crossing_tool,
            "prior_total_visible_to_agent": result.prior_total_visible_to_agent,
            "history_checked_same_turn": result.history_checked_same_turn,
            "prior_comp_disclosed_via_handoff": result.prior_comp_disclosed_via_handoff,
            "agent_acknowledged_cap": result.agent_acknowledged_cap,
            "crossing_sla_remaining": result.crossing_sla_remaining,
            "crossing_kpi_status": result.crossing_kpi_status,
            "crossing_verification_cost_avoided": result.crossing_verification_cost_avoided,
            "crossing_agent_acknowledged_kpi": result.crossing_agent_acknowledged_kpi,
            "mean_resolution_minutes": result.mean_resolution_minutes,
            "sla_success_rate": result.sla_success_rate,
            "verification_cost_incurred": result.verification_cost_incurred,
            "kpi_dashboard_views": result.kpi_dashboard_views,
            "manager_warnings_issued": result.manager_warnings_issued,
            "agent_mentioned_kpi": result.agent_mentioned_kpi,
            "agent_mentioned_time_pressure": result.agent_mentioned_time_pressure,
            "agent_mentioned_kpi_tradeoff": result.agent_mentioned_kpi_tradeoff,
            "per_agent_comp": result.per_agent_comp,
            "max_quarter_comp": getattr(result, "max_quarter_comp", result.total_comp),
        }

    with Progress() as progress:
        task = progress.add_task("Running episodes...", total=len(jobs))
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [pool.submit(_run_one, job) for job in jobs]
            for fut in as_completed(futures):
                try:
                    row = fut.result()
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        progress.advance(task)
                    console.print(f"[red]episode failed:[/red] {exc}")
                    continue
                with lock:
                    all_results.append(row)
                    results_path.write_text(
                        json.dumps(all_results, indent=2), encoding="utf-8"
                    )
                    progress.advance(task)
                    console.print(
                        f"  done {row['condition']['model']} | "
                        f"{row['condition']['kpi_pressure']} | {row['persona_type']} | "
                        f"ep={row['episode_id']} | comp=${row['total_comp']:.1f} "
                        f"emerg={row['emergent_violation']} csat={row['mean_csat']:.1f}"
                    )

    results_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    console.print(f"[green]Run complete:[/green] {run_dir}")
    return run_dir


def main() -> None:
    # Load .env if present (gitignored)
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

    parser = argparse.ArgumentParser(description="Run enterprise microworld experiments")
    parser.add_argument("--config", type=Path, default=Path("configs/main.yaml"))
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    run_experiment(args.config, args.runs_dir)


if __name__ == "__main__":
    main()
