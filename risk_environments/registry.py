"""Metadata for risk environments included in the unified framework."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RiskEnvironment:
    """Stable metadata required to discover and run a risk environment."""

    risk_id: str
    display_name: str
    package: str
    run_module: str
    smoke_config: str


_CONFIRMED_RISKS = {
    "kpi_gaming": RiskEnvironment(
        risk_id="kpi_gaming",
        display_name="KPI Gaming",
        package="orchestrator",
        run_module="run",
        smoke_config="configs/smoke.yaml",
    ),
    "authority_bias": RiskEnvironment(
        risk_id="authority_bias",
        display_name="Authority Bias",
        package="authority_deference",
        run_module="run_authority",
        smoke_config="configs/authority_smoke.yaml",
    ),
    "semantic_drift": RiskEnvironment(
        risk_id="semantic_drift",
        display_name="Semantic Drift",
        package="semantic_drift",
        run_module="run_drift",
        smoke_config="configs/drift_smoke.yaml",
    ),
    "d1": RiskEnvironment(
        risk_id="d1",
        display_name="D1 Confused Deputy",
        package="d1_confused_deputy",
        run_module="run_d1",
        smoke_config="configs/d1_smoke.yaml",
    ),
    "f1": RiskEnvironment(
        risk_id="f1",
        display_name="F1 Provenance Paradox",
        package="f1_provenance_paradox",
        run_module="run_f1",
        smoke_config="configs/f1_smoke.yaml",
    ),
}

CONFIRMED_RISKS: Mapping[str, RiskEnvironment] = MappingProxyType(
    _CONFIRMED_RISKS
)


def get_risk_environment(risk_id: str) -> RiskEnvironment:
    """Return a confirmed environment by its stable ID."""
    try:
        return CONFIRMED_RISKS[risk_id]
    except KeyError as exc:
        choices = ", ".join(CONFIRMED_RISKS)
        raise ValueError(
            f"Unknown or unconfirmed risk '{risk_id}'. Choose from: {choices}."
        ) from exc