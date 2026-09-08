"""Canonical registry for validated risk environments."""

from risk_environments.registry import (
    CONFIRMED_RISKS,
    RiskEnvironment,
    get_risk_environment,
)

__all__ = ["CONFIRMED_RISKS", "RiskEnvironment", "get_risk_environment"]