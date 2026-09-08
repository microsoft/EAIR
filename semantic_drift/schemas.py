"""Pydantic schemas for Semantic Drift artifacts (the simulation-layer
information objects agents produce and pass to each other)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

DiscountStatus = Literal["proposed", "in_review", "approved", "rejected"]
ApproverResponded = Literal["yes", "no", "not_requested"]
SalesAction = Literal["send", "edit_and_send", "hold"]
FinanceDecisionType = Literal["approve", "reject", "request_more_info"]


class CRMRecord(BaseModel):
    round: int
    customer_name: str
    discount_status: DiscountStatus
    discount_percent: Optional[float] = None
    notes: str = ""
    # rich_schema ablation only:
    authorized_approver: Optional[str] = None
    approver_responded: Optional[ApproverResponded] = None
    scope_note: Optional[str] = None
    unresolved_issues: Optional[str] = None


class ForecastOutput(BaseModel):
    round: int
    probability_pct: int
    rationale: str


class CustomerEmail(BaseModel):
    round: int
    subject: str
    body: str


class SalesDecision(BaseModel):
    action: SalesAction
    edited_body: Optional[str] = None
    note: Optional[str] = None


class EscalationRecord(BaseModel):
    round: int
    requesting_agent: str
    details: str
    decision: FinanceDecisionType
    decision_note: str = ""


class PingEvent(BaseModel):
    round: int
    trigger_texts_excerpt: str
    finance_note: str
