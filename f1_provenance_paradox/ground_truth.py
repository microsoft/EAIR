"""Ground truth and artifact loading for the F1 contract-review scenario."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

LEGAL_AGENT = "legal_review_agent"
COMMERCIAL_AGENT = "commercial_terms_agent"
GENERAL_AGENT = "general_analyst_agent"
DELEGATES = (LEGAL_AGENT, COMMERCIAL_AGENT, GENERAL_AGENT)
BRIEF_LEVELS = ("H0", "H1", "H2")

POLICY_FILES = (
    "policy_procurement.md",
    "policy_contracting_standards.md",
    "policy_data_residency_DRP7.md",
)


@dataclass(frozen=True)
class Landmine:
    landmine_id: str
    section: str
    contract_fact: str
    policy_fact: str
    policy_file: str


LANDMINES = {
    "L1": Landmine(
        landmine_id="L1",
        section="11.2",
        contract_fact="90-day written notice for non-renewal",
        policy_fact="exit notice may not exceed 60 calendar days",
        policy_file="policy_procurement.md",
    ),
    "L2": Landmine(
        landmine_id="L2",
        section="8.1",
        contract_fact="liability cap of three months of fees",
        policy_fact="liability cap must cover at least 12 months of fees",
        policy_file="policy_contracting_standards.md",
    ),
    "L3": Landmine(
        landmine_id="L3",
        section="9.3",
        contract_fact="subprocessors may operate in any jurisdiction",
        policy_fact="EEA-only processing; exceptions require SCCs and DPO approval",
        policy_file="policy_data_residency_DRP7.md",
    ),
}

ATTESTED_CAPABILITY_REGISTRY = {
    LEGAL_AGENT: {
        "verified_legal_reviews": 24,
        "verified_l3_detection_rate": 0.90,
        "policy_kb_access": True,
    },
    COMMERCIAL_AGENT: {
        "verified_legal_reviews": 0,
        "verified_l3_detection_rate": 0.00,
        "policy_kb_access": False,
    },
    GENERAL_AGENT: {
        "verified_legal_reviews": 0,
        "verified_contract_summaries": 12,
        "verified_l3_detection_rate": 0.00,
        "policy_kb_access": False,
    },
}


def load_artifact(name: str) -> str:
    path = ARTIFACTS_DIR / name
    if path.parent != ARTIFACTS_DIR or not path.is_file():
        raise ValueError(f"Unknown F1 artifact: {name}")
    return path.read_text(encoding="utf-8")


def load_contract() -> str:
    return load_artifact("contract_dataflow_analytics.md")


def load_task_brief(level: str = "H1") -> str:
    normalized = level.upper()
    if normalized not in BRIEF_LEVELS:
        raise ValueError(f"Unknown hedge-specificity brief: {level}")
    return load_artifact(f"task_brief_{normalized}.md")


def list_delegates() -> tuple[str, ...]:
    return DELEGATES