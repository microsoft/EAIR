"""Pydantic schemas for the Authority Deference Bias micro-world artifacts.

These are the simulation-layer objects the agents produce and the auditable
records the orchestrator writes out. Kept 3.9-compatible (Optional/List) to
match the rest of the repo.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

# The four downstream agents, in pipeline order. The Reporter is scripted and
# is not an LLM agent, so it is not listed here.
DOWNSTREAM_AGENTS = [
    "sre_agent",
    "customer_support_agent",
    "legal_agent",
    "report_writer_agent",
]

# The report-section field each agent is asked to submit.
AGENT_REPORT_FIELDS = {
    "sre_agent": ["root_cause_technical"],
    "customer_support_agent": ["customer_comms_draft"],
    "legal_agent": ["legal_assessment"],
    "report_writer_agent": ["root_cause", "executive_summary"],
}


class EvidenceAccess(BaseModel):
    """One read_logs / read_document tool call, logged with agent + timestamp
    (spec: 'LOG EVERY CALL with agent name + timestamp')."""

    order: int
    agent: str
    tool: str  # "read_logs" | "read_document"
    target: str  # source or document name
    step: int
    timestamp: str


class ChannelPost(BaseModel):
    """One message posted to the shared incident channel."""

    order: int
    sender: str  # agent role, "reporter", or "system"
    label: str  # display label shown to downstream agents
    content: str
    step: int


class ReportSection(BaseModel):
    """A submitted incident-report section."""

    order: int
    agent: str
    field: str
    content: str
    step: int


class AgentActivity(BaseModel):
    """Per-agent derived summary used by metrics (all values come straight
    from the auditable action log; nothing is inferred by an LLM here)."""

    agent: str
    read_deployment: bool = False
    read_api_errors: bool = False
    read_vendor_status: bool = False
    read_sla_contract: bool = False
    read_runbook: bool = False
    # Did the agent read deployment OR api_errors BEFORE its first submission?
    checked_core_evidence_before_submit: bool = False
    submitted_fields: List[str] = []
