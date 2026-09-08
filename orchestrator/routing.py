"""Hybrid front-door routing helpers: default support, specialist on clear intent."""

from __future__ import annotations

import re
from typing import Any, Optional

RETENTION_PATTERNS = [
    r"\bcancel(?:l?ing|led|lation)?\b",
    r"\bchurn\b",
    r"\bterminat(?:e|ing|ion)\b",
    r"\bclose my (?:account|service)\b",
    r"\bswitch(?:ing)? (?:to )?(?:a )?competitor\b",
    r"\bretention\b",
    r"退订|取消(?:套餐|服务|合约)?|销户",
]

BILLING_PATTERNS = [
    r"\bbilling\b",
    r"\binvoice\b",
    r"\bcharge[ds]?\b",
    r"\bovercharg(?:e|ed|ing)\b",
    r"\brefund\b",
    r"\bdisput(?:e|ing)\b",
    r"账单|扣款|发票|费用争议|多收",
]


def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text or "", flags=re.IGNORECASE) for p in patterns)


def detect_specialist_trigger(text: str) -> Optional[str]:
    """Return 'retention_agent' / 'billing_agent' if keywords fire, else None.

    If both match, retention wins when cancel-language is present; else billing.
    """
    text = text or ""
    ret = _matches(text, RETENTION_PATTERNS)
    bil = _matches(text, BILLING_PATTERNS)
    if ret and not bil:
        return "retention_agent"
    if bil and not ret:
        return "billing_agent"
    if ret and bil:
        # Prefer retention if cancellation is explicit.
        if re.search(r"cancel|退订|取消|销户", text, re.IGNORECASE):
            return "retention_agent"
        return "billing_agent"
    return None


def initial_role_for_front_door(contact: dict[str, Any]) -> str:
    """Default support; skip to specialist when the contact is clearly theirs.

    - Explicit retention/billing intent or case_type → that specialist.
    - Optional contact['entry_point'] == 'support' forces the front desk
      (used for handoff-probe scripts that must start at support).
    - Otherwise start at support (even if the opening also mentions cancel —
      support then handoffs mid-flow / on triage).
    """
    if (contact or {}).get("assigned_role"):
        return str(contact["assigned_role"])
    if (contact or {}).get("entry_point") == "support":
        return "support_agent"

    intent = (contact or {}).get("intent", "outage")
    case_type = (contact or {}).get("case_type", "")
    issue = (contact or {}).get("issue_category", "")

    if intent == "cancellation" or issue == "retention" or "retention" in str(case_type):
        return "retention_agent"
    if intent == "billing_dispute" or issue == "billing_dispute" or case_type == "billing_dispute":
        return "billing_agent"

    return "support_agent"


def mid_conversation_handoff_nudge(agent_role: str, customer_text: str) -> str:
    """Instruction fragment when support should escalate on keyword triggers."""
    if agent_role != "support_agent":
        return ""
    target = detect_specialist_trigger(customer_text)
    if target == "retention_agent":
        return (
            " The customer's latest message indicates cancellation / retention "
            "intent. You MUST call send_handoff to retention_agent now; do not "
            "try to save the account yourself."
        )
    if target == "billing_agent":
        return (
            " The customer's latest message indicates a billing dispute. "
            "You MUST call send_handoff to billing_agent now; do not resolve "
            "billing yourself."
        )
    return ""
