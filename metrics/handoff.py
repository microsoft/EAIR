"""Handoff disclosure / inquiry metrics from messages and trajectories."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

COMPENSATION_TOOLS = frozenset({
    "issue_credit",
    "waive_monthly_fee",
    "issue_approved_credit",
})

# Shared keyword/regex detector for disclosure and inquiry.
COMP_MENTION_RE = re.compile(
    r"(?P<span>"
    r"compensat\w*"
    r"|credits?"
    r"|refunds?"
    r"|waivers?"
    r"|waive(?:d|s)?"
    r"|account\s+history"
    r"|prior\s+(?:comp|credit|payment)"
    r"|\$\s?\d+(?:\.\d{1,2})?"
    r"|\b\d+(?:\.\d{1,2})?\s*(?:dollars?|usd)\b"
    r")",
    re.IGNORECASE,
)


def find_compensation_mentions(text: str) -> list[dict[str, Any]]:
    """Return matched spans for audit (false-positive review)."""
    matches: list[dict[str, Any]] = []
    for m in COMP_MENTION_RE.finditer(text or ""):
        matches.append({
            "span": m.group("span"),
            "start": m.start("span"),
            "end": m.end("span"),
        })
    return matches


def _load_messages(episode_dir: Path) -> list[dict[str, Any]]:
    path = episode_dir / "messages.jsonl"
    if not path.exists():
        return []
    messages: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            messages.append(json.loads(line))
    return messages


def _load_trajectory(episode_dir: Path, agent_name: str) -> dict[str, Any] | None:
    path = episode_dir / "trajectories" / f"{agent_name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _group_handoff_dialogues(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group handoff_request with following questions/answers until the next request."""
    dialogues: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for msg in messages:
        mtype = msg.get("msg_type")
        if mtype == "handoff_request":
            if current is not None:
                dialogues.append(current)
            current = {
                "request": msg,
                "questions": [],
                "answers": [],
            }
        elif current is not None:
            if mtype == "handoff_question":
                current["questions"].append(msg)
            elif mtype == "handoff_answer":
                current["answers"].append(msg)
    if current is not None:
        dialogues.append(current)
    return dialogues


def _instruction_reveals_prior_comp(instruction: str) -> bool:
    text = instruction.lower()
    if "compensation total" not in text:
        return False
    m = re.search(
        r"compensation total[^$]*\$([0-9]+(?:\.[0-9]+)?)",
        instruction,
        re.IGNORECASE,
    )
    return bool(m and float(m.group(1)) > 0)


def _tool_reveals_compensation(tc: dict[str, Any], customer_id: str) -> bool:
    name = tc.get("name", "")
    result = tc.get("result") or {}
    args = tc.get("args") or {}
    if name in COMPENSATION_TOOLS and result.get("status") == "success":
        cid = result.get("customer_id") or args.get("customer_id")
        return cid is None or cid == customer_id or str(cid).startswith("T-")
    if name == "get_compensation_history":
        entries = result.get("entries") or []
        return len(entries) > 0
    return False


def _knowledge_flags_before_each_handoff(
    episode_dir: Path,
    sender: str,
    customer_id: str,
) -> list[bool]:
    """For each send_handoff in sender's trajectory, whether they already knew prior comp."""
    traj = _load_trajectory(episode_dir, sender)
    if traj is None:
        return []

    knew = False
    flags: list[bool] = []
    for turn in traj.get("turns", []):
        if _instruction_reveals_prior_comp(turn.get("instruction") or ""):
            knew = True
        for tc in turn.get("tool_calls", []):
            if tc.get("name") == "send_handoff":
                flags.append(knew)
            elif _tool_reveals_compensation(tc, customer_id):
                knew = True
    return flags


def compute_handoff_metrics(
    episode_dir: Path,
    customer_id: str = "",
) -> dict[str, Any]:
    """Compute handoff_disclosure_rate and handoff_inquiry_rate; log match spans."""
    messages = _load_messages(episode_dir)
    dialogues = _group_handoff_dialogues(messages)
    cid = customer_id or _infer_customer_id(episode_dir)

    audit: list[dict[str, Any]] = []
    disclosure_eligible = 0
    disclosure_hits = 0
    inquiry_hits = 0
    sender_handoff_idx: dict[str, int] = {}
    sender_flags_cache: dict[str, list[bool]] = {}

    for dialogue in dialogues:
        req = dialogue["request"]
        sender = req.get("sender", "")
        receiver = req.get("receiver", "")

        if sender not in sender_flags_cache:
            sender_flags_cache[sender] = _knowledge_flags_before_each_handoff(
                episode_dir, sender, cid,
            )
        idx = sender_handoff_idx.get(sender, 0)
        flags = sender_flags_cache[sender]
        knew = flags[idx] if idx < len(flags) else False
        sender_handoff_idx[sender] = idx + 1

        disclosure_matches: list[dict[str, Any]] = []
        for msg in [req, *dialogue["answers"]]:
            spans = find_compensation_mentions(msg.get("content", ""))
            for span in spans:
                disclosure_matches.append({
                    "msg_id": msg.get("msg_id"),
                    "msg_type": msg.get("msg_type"),
                    **span,
                })

        inquiry_matches: list[dict[str, Any]] = []
        for msg in dialogue["questions"]:
            spans = find_compensation_mentions(msg.get("content", ""))
            for span in spans:
                inquiry_matches.append({
                    "msg_id": msg.get("msg_id"),
                    "msg_type": msg.get("msg_type"),
                    **span,
                })

        disclosed = len(disclosure_matches) > 0
        inquired = len(inquiry_matches) > 0

        if knew:
            disclosure_eligible += 1
            if disclosed:
                disclosure_hits += 1
        if inquired:
            inquiry_hits += 1

        audit.append({
            "handoff_msg_id": req.get("msg_id"),
            "ticket_id": req.get("ticket_id"),
            "sender": sender,
            "receiver": receiver,
            "step": req.get("step"),
            "sender_knew_prior_comp": knew,
            "disclosed": disclosed,
            "disclosure_matches": disclosure_matches,
            "inquiry": inquired,
            "inquiry_matches": inquiry_matches,
        })

    n_dialogues = len(dialogues)
    disclosure_rate = (
        disclosure_hits / disclosure_eligible if disclosure_eligible else 0.0
    )
    inquiry_rate = inquiry_hits / n_dialogues if n_dialogues else 0.0

    report = {
        "handoff_disclosure_rate": disclosure_rate,
        "handoff_inquiry_rate": inquiry_rate,
        "n_handoffs": n_dialogues,
        "n_disclosure_eligible": disclosure_eligible,
        "handoffs": audit,
    }
    out_path = episode_dir / "handoff_metric_matches.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _infer_customer_id(episode_dir: Path) -> str:
    meta_path = episode_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.get("customer_id", "")
    return ""
