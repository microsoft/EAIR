"""Pydantic schemas for inter-agent communication."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

SenderRole = Literal[
    "customer",
    "support_agent",
    "retention_agent",
    "billing_agent",
    "finance_approver",
    "orchestrator",
]

MessageType = Literal[
    "customer_message",
    "agent_reply",
    "handoff_request",
    "handoff_question",
    "handoff_answer",
    "approval_request",
    "approval_question",
    "approval_answer",
    "approval_decision",
    "system_notice",
    # Semantic Drift micro-world message types (additive; see
    # semantic_drift/orchestrator.py).
    "meeting_transcript",
    "deal_summary",
    "crm_update",
    "forecast_output",
    "customer_email_draft",
    "sales_decision",
    "customer_reply",
    "pricing_exception_request",
    "finance_decision",
    "finance_status_inquiry",
    "finance_status_response",
    # Authority Deference Bias micro-world message types (additive; see
    # authority_deference/orchestrator.py).
    "incident_channel",
    "incident_post",
    "report_section",
    # Permission Drift / Confused Deputy micro-world message types.
    "user_request",
    "specialist_handoff",
    "specialist_reply",
    "final_to_requester",
    # F1 Provenance Paradox micro-world message types.
    "capability_request",
    "competitive_bids",
    "capability_statement",
    "review_assignment",
    "review_report",
    "executive_summary",
    # A2 Reciprocal Approval Collusion micro-world message types.
    "daily_approval_queue",
]


class Message(BaseModel):
    """Single message exchanged on the message bus."""

    msg_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    episode_id: str
    ticket_id: Optional[str] = None
    step: int
    sender: Union[SenderRole, str]
    receiver: Union[SenderRole, str]
    msg_type: MessageType
    content: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def memory_key(self) -> str:
        """Unique key for deduplication in agent memory."""
        return self.msg_id
