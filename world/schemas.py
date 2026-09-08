"""Pydantic schemas for world state."""

from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

IssueCategory = Literal["outage", "billing_dispute", "retention", "goodwill"]
TicketStatus = Literal["open", "closed", "transferred"]
AgentRole = Literal[
    "support_agent",
    "retention_agent",
    "billing_agent",
    "service_recovery_agent",
    "escalation_agent",
    "finance_approver",
]


class Customer(BaseModel):
    """Synthetic enterprise customer."""

    customer_id: str
    name: str
    plan: str
    tenure_months: int


class InvoiceLine(BaseModel):
    """Authoritative invoice line used to validate billing disputes."""

    invoice_line_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str
    ticket_id: str
    description: str
    amount: float
    charged_date: str
    is_erroneous: bool
    dispute_candidate: bool = False
    adjusted_amount: float = 0.0


class InvoiceAdjustment(BaseModel):
    """A refund applied against one authoritative invoice line."""

    adjustment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    invoice_line_id: str
    customer_id: str
    agent_role: str
    amount: float
    reason_code: str
    ticket_id: str
    step: int
    ground_truth_is_erroneous: bool
    policy_violation: bool
    adjusted_date: str = ""


class CompensationEntry(BaseModel):
    """Append-only ledger entry for customer compensation.

    ``reason_code`` is whatever the agent declared. ``actual_reason`` is
    orchestrator ground truth (not exposed by get_compensation_history).

    ``issued_date`` is the simulated calendar date when the credit was issued
    (used for calendar-quarter cap accounting). Legacy field name ``date`` is
    accepted on load.
    """

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str
    agent_role: str
    amount: float
    reason_code: str
    actual_reason: IssueCategory
    ticket_id: str
    step: int
    issued_date: str = ""  # ISO date in simulated time when credit was issued

    @model_validator(mode="before")
    @classmethod
    def _legacy_date_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("issued_date") and data.get("date"):
                data = {**data, "issued_date": data["date"]}
        return data


class Ticket(BaseModel):
    """Customer service ticket / case. Closed tickets are never reopened."""

    ticket_id: str
    customer_id: str
    issue_category: IssueCategory
    status: TicketStatus = "open"
    assigned_role: str
    opened_date: str = ""  # ISO date customer opened this request (simulated)
    closed_date: Optional[str] = None
