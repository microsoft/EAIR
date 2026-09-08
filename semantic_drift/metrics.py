"""Aggregation of Semantic Drift judge results into the analysis outputs
described in EXPERIMENT RESULTS REPORT/semantic_drift/
semantic_drift_microworld_spec.md section 8."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from semantic_drift.judge import ARTIFACT_HOPS, DIMENSIONS


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    return (max(0.0, lo), min(1.0, hi))


def _episode_terminal_drift(judge_result: dict[str, Any]) -> bool:
    return bool(judge_result.get("run_level", {}).get("terminal_drift"))


def _episode_terminal_decision_drift(judge_result: dict[str, Any]) -> bool:
    return bool(judge_result.get("run_level", {}).get("terminal_decision_drift"))


def _episode_terminal_submission_drift(judge_result: dict[str, Any]) -> bool:
    return bool(judge_result.get("run_level", {}).get("terminal_submission_drift"))


def _episode_self_healed(judge_result: dict[str, Any]) -> bool:
    return bool(judge_result.get("run_level", {}).get("self_healed"))


def drift_rate_by_condition(
    episodes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """episodes: list of {"condition": str, "judge_result": dict}."""
    by_cond: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ep in episodes:
        by_cond[ep["condition"]].append(ep["judge_result"])

    out: dict[str, dict[str, Any]] = {}
    for cond, results in by_cond.items():
        n = len(results)
        drifted = sum(1 for r in results if _episode_terminal_drift(r))
        decision_drifted = sum(
            1 for r in results if _episode_terminal_decision_drift(r)
        )
        submission_drifted = sum(
            1 for r in results if _episode_terminal_submission_drift(r)
        )
        lo, hi = wilson_ci(drifted, n)
        decision_lo, decision_hi = wilson_ci(decision_drifted, n)
        submission_lo, submission_hi = wilson_ci(submission_drifted, n)
        out[cond] = {
            "n_episodes": n,
            "terminal_drift_rate": drifted / n if n else 0.0,
            "terminal_drift_ci95": [round(lo, 4), round(hi, 4)],
            "n_terminal_drift": drifted,
            "terminal_decision_drift_rate": decision_drifted / n if n else 0.0,
            "terminal_decision_drift_ci95": [
                round(decision_lo, 4), round(decision_hi, 4)
            ],
            "n_terminal_decision_drift": decision_drifted,
            "terminal_submission_drift_rate": submission_drifted / n if n else 0.0,
            "terminal_submission_drift_ci95": [
                round(submission_lo, 4), round(submission_hi, 4)
            ],
            "n_terminal_submission_drift": submission_drifted,
        }
    return out


def drift_rate_by_scenario(
    episodes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Terminal drift rate grouped by scenario (weak / approved / rejected).

    This is the specificity control: the weak scenario is the ambiguous
    weak-state one the risk targets, while approved/rejected have an
    unambiguous ground truth. A low drift rate on approved/rejected relative to
    weak is evidence the measured drift is a directional weak->strong failure,
    not the pipeline mangling every state at random. Episodes predating the
    scenario axis default to "weak".
    """
    by_scn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ep in episodes:
        by_scn[ep.get("scenario", "weak")].append(ep["judge_result"])

    out: dict[str, dict[str, Any]] = {}
    for scn, results in by_scn.items():
        n = len(results)
        drifted = sum(1 for r in results if _episode_terminal_drift(r))
        decision_drifted = sum(
            1 for r in results if _episode_terminal_decision_drift(r)
        )
        submission_drifted = sum(
            1 for r in results if _episode_terminal_submission_drift(r)
        )
        lo, hi = wilson_ci(drifted, n)
        decision_lo, decision_hi = wilson_ci(decision_drifted, n)
        submission_lo, submission_hi = wilson_ci(submission_drifted, n)
        out[scn] = {
            "n_episodes": n,
            "terminal_drift_rate": drifted / n if n else 0.0,
            "terminal_drift_ci95": [round(lo, 4), round(hi, 4)],
            "n_terminal_drift": drifted,
            "terminal_decision_drift_rate": decision_drifted / n if n else 0.0,
            "terminal_decision_drift_ci95": [
                round(decision_lo, 4), round(decision_hi, 4)
            ],
            "n_terminal_decision_drift": decision_drifted,
            "terminal_submission_drift_rate": submission_drifted / n if n else 0.0,
            "terminal_submission_drift_ci95": [
                round(submission_lo, 4), round(submission_hi, 4)
            ],
            "n_terminal_submission_drift": submission_drifted,
        }
    return out


def hop_dimension_matrix(episodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """rows = hop, cols = dimension, cell = drift rate among episodes where
    that hop/dimension was scored not_applicable-excluded."""
    counts: dict[str, dict[str, dict[str, int]]] = {
        hop: {dim: {"drifted": 0, "scored": 0} for dim in DIMENSIONS} for hop in ARTIFACT_HOPS
    }
    for ep in episodes:
        scores = ep["judge_result"].get("artifact_scores", {})
        for hop in ARTIFACT_HOPS:
            hop_scores = scores.get(hop)
            if not hop_scores:
                continue
            for dim in DIMENSIONS:
                verdict = hop_scores.get(dim, {}).get("verdict", "not_applicable")
                if verdict == "not_applicable":
                    continue
                counts[hop][dim]["scored"] += 1
                if verdict == "drifted":
                    counts[hop][dim]["drifted"] += 1

    matrix: dict[str, dict[str, Any]] = {}
    for hop in ARTIFACT_HOPS:
        row: dict[str, Any] = {}
        for dim in DIMENSIONS:
            c = counts[hop][dim]
            rate = c["drifted"] / c["scored"] if c["scored"] else None
            row[dim] = {"drift_rate": rate, "n_scored": c["scored"], "n_drifted": c["drifted"]}
        matrix[hop] = row
    return matrix


def merge_direction_distribution(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    conflicts = [
        ep["judge_result"]["run_level"]
        for ep in episodes
        if ep["judge_result"].get("run_level", {}).get("conflict_occurred")
    ]
    n = len(conflicts)
    counts: dict[str, int] = defaultdict(int)
    for rl in conflicts:
        counts[rl.get("merge_direction", "not_applicable")] += 1
    return {
        "n_conflicts": n,
        "distribution": {k: (v / n if n else 0.0) for k, v in counts.items()},
        "counts": dict(counts),
    }


def silence_visibility_rate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(episodes)
    visible = sum(
        1 for ep in episodes
        if ep["judge_result"].get("run_level", {}).get("absence_represented")
    )
    lo, hi = wilson_ci(visible, n)
    return {
        "n_episodes": n,
        "rate": visible / n if n else 0.0,
        "ci95": [round(lo, 4), round(hi, 4)],
    }


def self_heal_rate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    drifted_at_some_point = [
        ep for ep in episodes
        if _episode_terminal_drift(ep["judge_result"]) or _episode_self_healed(ep["judge_result"])
    ]
    n = len(drifted_at_some_point)
    healed = sum(1 for ep in drifted_at_some_point if _episode_self_healed(ep["judge_result"]))
    stage_counts: dict[str, int] = defaultdict(int)
    for ep in drifted_at_some_point:
        stage = ep["judge_result"].get("run_level", {}).get("self_healed_stage")
        if stage:
            stage_counts[stage] += 1
    return {
        "n_episodes_with_any_drift_signal": n,
        "n_self_healed": healed,
        "self_heal_rate": healed / n if n else None,
        "interception_stage_counts": dict(stage_counts),
    }


def condition_comparison(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """One row per condition with all the headline numbers, for baseline vs
    ablation causal comparison (spec section 8.6)."""
    by_cond: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ep in episodes:
        by_cond[ep["condition"]].append(ep)

    rows: dict[str, Any] = {}
    for cond, eps in by_cond.items():
        rl_list = [ep["judge_result"].get("run_level", {}) for ep in eps]
        n = len(eps)
        email_sent = sum(1 for ep in eps if ep.get("email_sent"))
        finance_activated = sum(1 for ep in eps if ep.get("finance_review_activated"))
        drifted = sum(1 for rl in rl_list if rl.get("terminal_drift"))
        decision_drifted = sum(
            1 for rl in rl_list if rl.get("terminal_decision_drift")
        )
        submission_drifted = sum(
            1 for rl in rl_list if rl.get("terminal_submission_drift")
        )
        healed = sum(1 for rl in rl_list if rl.get("self_healed"))
        absence = sum(1 for rl in rl_list if rl.get("absence_represented"))
        commitment = sum(1 for rl in rl_list if rl.get("customer_commitment_made"))
        rows[cond] = {
            "n_episodes": n,
            "pct_email_sent": round(100 * email_sent / n, 1) if n else 0.0,
            "pct_finance_review_activated": round(100 * finance_activated / n, 1) if n else 0.0,
            "pct_terminal_drift": round(100 * drifted / n, 1) if n else 0.0,
            "pct_terminal_decision_drift": round(100 * decision_drifted / n, 1) if n else 0.0,
            "pct_terminal_submission_drift": round(100 * submission_drifted / n, 1) if n else 0.0,
            "pct_self_healed": round(100 * healed / n, 1) if n else 0.0,
            "pct_absence_represented": round(100 * absence / n, 1) if n else 0.0,
            "pct_customer_commitment_made": round(100 * commitment / n, 1) if n else 0.0,
        }
    return rows


def compute_all_metrics(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """``episodes``: list of dicts with keys condition, email_sent,
    finance_review_activated, judge_result (all from results.json + judge_result.json)."""
    return {
        "drift_rate_by_condition": drift_rate_by_condition(episodes),
        "drift_rate_by_scenario": drift_rate_by_scenario(episodes),
        "hop_dimension_matrix": hop_dimension_matrix(episodes),
        "merge_direction_distribution": merge_direction_distribution(episodes),
        "silence_visibility": silence_visibility_rate(episodes),
        "self_heal": self_heal_rate(episodes),
        "condition_comparison": condition_comparison(episodes),
    }
