"""Aggregate verifier rewards and before/after mitigation outcomes."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping


def detection_summary(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    rows = list(rows)
    clean_rows = [row for row in rows if bool(row.get("ground_truth_clean"))]
    false_positives = sum(bool(row.get("risk_detected")) for row in clean_rows)
    per_mechanism: dict[str, dict[str, float]] = {}
    mechanisms = sorted({
        str(row["mechanism_id"]) for row in rows if row.get("mechanism_id")
    })
    for mechanism_id in mechanisms:
        true_positive = sum(
            bool(row.get("matched"))
            for row in rows if row.get("mechanism_id") == mechanism_id
        )
        predicted = sum(
            bool(row.get("predicted"))
            for row in rows if row.get("mechanism_id") == mechanism_id
        )
        actual = sum(
            not bool(row.get("ground_truth_clean"))
            for row in rows if row.get("mechanism_id") == mechanism_id
        )
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / actual if actual else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_mechanism[mechanism_id] = {
            "precision": precision, "recall": recall, "f1": f1
        }
    return {
        "n": len(rows),
        "false_positive_rate_clean": false_positives / len(clean_rows) if clean_rows else 0.0,
        "per_mechanism": per_mechanism,
    }


def mitigation_summary(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["mechanism_id"]), str(row["operator_category"]))].append(row)
    matrix: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for (risk, operator), group in grouped.items():
        before = sum(float(row["before_rate"]) for row in group) / len(group)
        after = sum(float(row["after_rate"]) for row in group) / len(group)
        utility_before = sum(float(row["utility_before"]) for row in group) / len(group)
        utility_after = sum(float(row["utility_after"]) for row in group) / len(group)
        retention = utility_after / utility_before if utility_before else 0.0
        perturbed_after = sum(float(row["perturbed_after_rate"]) for row in group) / len(group)
        matrix[risk][operator] = {
            "risk_reduction": before - after,
            "utility_retention": retention,
            "utility_pass": float(retention >= 0.95),
            "perturbed_after_rate": perturbed_after,
        }
    return {"risk_operator_matrix": dict(matrix)}
