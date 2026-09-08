"""Aggregate F1 provenance paradox metrics, preferring valid semantic judgments."""

from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from f1_provenance_paradox.metrics import aggregate_results
from run_f1_calibration import aggregate_calibration

console = Console()


def _merge_judgments(
    rows: list[dict[str, Any]],
    run_dir: Path,
) -> tuple[list[dict[str, Any]], int]:
    judge_path = run_dir / "judge_results.json"
    if not judge_path.exists():
        return rows, 0
    judge_rows = json.loads(judge_path.read_text(encoding="utf-8"))
    judgments = {
        row["episode_id"]: row["judge_result"]
        for row in judge_rows
        if not row.get("judge_result", {}).get("parse_error")
    }
    merged = deepcopy(rows)
    applied = 0
    for row in merged:
        judgment = judgments.get(row["episode_id"])
        if not judgment:
            continue
        semantic = judgment["semantic_verifier"]
        if row.get("mode") == "solo_calibration":
            row["landmines"] = semantic["landmine_scores"]
            applied += 1
            continue
        row["verifier"]["landmines"] = semantic["landmine_scores"]
        row["verifier"]["cascade_depth"] = semantic["cascade_depth"]
        row["verifier"]["provenance_retained"] = semantic[
            "provenance_retained"
        ]["value"]
        row["verifier"]["risk_triggered"] = semantic["risk_triggered"]
        revision = semantic.get("competitive_bid_revision", {})
        row["verifier"]["semantic_generalist_assertiveness_revision"] = (
            revision.get("score") if revision.get("applicable") else None
        )
        oracle_legal_l3 = row["verifier"].get("oracle_legal_l3")
        if oracle_legal_l3 is not None:
            row["verifier"]["counterfactual_regret"] = max(
                0.0,
                float(oracle_legal_l3) - float(semantic["landmine_scores"]["L3"]),
            )
        applied += 1
    return merged, applied


def analyze(run_dir: Path) -> dict[str, Any]:
    results_path = run_dir / "results.json"
    if not results_path.exists():
        raise FileNotFoundError(f"Missing F1 results file: {results_path}")
    rows = json.loads(results_path.read_text(encoding="utf-8"))
    merged, judgments_applied = _merge_judgments(rows, run_dir)
    if rows and all(row.get("mode") == "solo_calibration" for row in rows):
        summary = aggregate_calibration(merged)
        summary["semantic_judgments_applied"] = judgments_applied
        (run_dir / "calibration_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        console.print(
            f"F1 calibration summary: {summary['n_reviews']} reviews; "
            f"semantic judgments applied: {judgments_applied}"
        )
        return summary
    summary = aggregate_results(merged)
    summary["semantic_judgments_applied"] = judgments_applied
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    _write_csv(run_dir / "summary.csv", summary)
    _print_summary(summary)
    return summary


def _write_csv(path: Path, summary: dict[str, Any]) -> None:
    rows = []
    for condition in summary["conditions"].values():
        rows.append({
            "model": condition["model"],
            "condition": condition["condition_name"],
            "n_episodes": condition["n_episodes"],
            "misrouting_rate": condition["misrouting_rate"],
            "misrouting_ci95_low": condition["misrouting_ci95"][0],
            "misrouting_ci95_high": condition["misrouting_ci95"][1],
            "self_promotion_route_rate": condition["self_promotion_route_rate"],
            "full_cascade_trigger_rate": condition["full_cascade_trigger_rate"],
            "full_cascade_trigger_ci95_low": condition[
                "full_cascade_trigger_ci95"
            ][0],
            "full_cascade_trigger_ci95_high": condition[
                "full_cascade_trigger_ci95"
            ][1],
            "l1_detection_rate": condition["landmine_detection_rate"]["L1"],
            "l2_detection_rate": condition["landmine_detection_rate"]["L2"],
            "l3_detection_rate": condition["landmine_detection_rate"]["L3"],
            "landmine_detection_ci95": json.dumps(
                condition["landmine_detection_ci95"], sort_keys=True
            ),
            "complete_cascade_rate": condition["complete_cascade_rate"],
            "complete_cascade_ci95_low": condition["complete_cascade_ci95"][0],
            "complete_cascade_ci95_high": condition["complete_cascade_ci95"][1],
            "provenance_retention_rate": condition["provenance_retention_rate"],
            "provenance_retention_ci95_low": condition[
                "provenance_retention_ci95"
            ][0],
            "provenance_retention_ci95_high": condition[
                "provenance_retention_ci95"
            ][1],
            "mean_counterfactual_regret": condition["mean_counterfactual_regret"],
            "mean_counterfactual_regret_ci95": json.dumps(
                condition["mean_counterfactual_regret_ci95"]
            ),
            "mean_generalist_confidence_revision": condition[
                "mean_generalist_confidence_revision"
            ],
            "mean_generalist_assertiveness_revision": condition[
                "mean_generalist_assertiveness_revision"
            ],
            "mean_overclaim_gap": json.dumps(
                condition["mean_overclaim_gap"], sort_keys=True
            ),
            "mean_overclaim_gap_ci95": json.dumps(
                condition["mean_overclaim_gap_ci95"], sort_keys=True
            ),
            "landmine_detection_by_selected_agent": json.dumps(
                condition["landmine_detection_by_selected_agent"], sort_keys=True
            ),
        })
    fieldnames = list(rows[0]) if rows else ["model", "condition", "n_episodes"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _print_summary(summary: dict[str, Any]) -> None:
    table = Table(title=f"F1 Summary ({summary['n_episodes']} episodes)")
    for column in (
        "Model", "Condition", "N", "Misroute", "Self-promotion route",
        "L3 detect", "Full cascade", "Provenance retained",
    ):
        table.add_column(column)
    for condition in summary["conditions"].values():
        table.add_row(
            condition["model"],
            condition["condition_name"],
            str(condition["n_episodes"]),
            f"{condition['misrouting_rate']:.1%}",
            f"{condition['self_promotion_route_rate']:.1%}",
            f"{condition['landmine_detection_rate']['L3']:.1%}",
            f"{condition['full_cascade_trigger_rate']:.1%}",
            f"{condition['provenance_retention_rate']:.1%}",
        )
    console.print(table)
    console.print(
        f"Semantic judgments applied: {summary['semantic_judgments_applied']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze an F1 experiment run")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    analyze(args.run_dir)


if __name__ == "__main__":
    main()