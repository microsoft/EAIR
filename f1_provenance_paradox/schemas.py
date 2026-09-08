"""Structured information objects produced by F1 agents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["low", "med", "high"]
DelegateName = Literal[
    "legal_review_agent",
    "commercial_terms_agent",
    "general_analyst_agent",
]


class CapabilityBid(BaseModel):
    agent: DelegateName
    expertise_claim: str
    confidence: Confidence
    eta_hours: float = Field(gt=0)
    cost_usd: float = Field(ge=0)
    statement: str


class RoutingDecision(BaseModel):
    selected_agent: DelegateName
    reasoning: str
    confidence: Confidence


class ReviewReport(BaseModel):
    report: str
    recommendation: Literal["SIGN", "REJECT", "ESCALATE"]


class ExecutiveSummary(BaseModel):
    summary: str
    recommendation: Literal["SIGN", "REJECT", "ESCALATE"]
    unresolved_risks: list[str] = Field(default_factory=list)


class ApprovalVerdict(BaseModel):
    decision: Literal["SIGN", "REJECT", "ESCALATE"]
    reasoning: str