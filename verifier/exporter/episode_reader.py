"""Convert globally ordered environment events into verifier trajectories."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.memory import Trajectory as AgentTrajectory
from verifier.schemas.trajectory import Message, Trajectory


class LegacyEpisodeError(ValueError):
    """An episode lacks the records required for deterministic legacy export."""


MESSAGE_CHANNELS = {
    "handoff_request": "handoff",
    "handoff_question": "handoff",
    "handoff_answer": "handoff",
    "specialist_handoff": "handoff",
    "specialist_reply": "handoff",
    "review_assignment": "handoff",
    "approval_request": "approval_request",
    "pricing_exception_request": "approval_request",
    "approval_decision": "approval_decision",
    "finance_decision": "approval_decision",
    "deal_summary": "summary",
    "crm_update": "summary",
    "forecast_output": "summary",
    "executive_summary": "summary",
    "review_report": "summary",
    "report_section": "summary",
}


def _load_events(path: Path, episode_id: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise LegacyEpisodeError(
            f"{path.parent} has no events.jsonl"
        )
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sequences = [event.get("event_seq") for event in events]
    if sequences != list(range(1, len(events) + 1)):
        raise ValueError("events.jsonl must have contiguous event_seq values starting at 1")
    if any(event.get("episode_id") != episode_id for event in events):
        raise ValueError("events.jsonl contains a different episode_id")
    return events


def _timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_legacy_messages(episode_dir: Path, episode_id: str) -> list[dict[str, Any]]:
    path = episode_dir / "messages.jsonl"
    if not path.is_file():
        raise LegacyEpisodeError(
            f"{episode_dir} has neither events.jsonl nor messages.jsonl"
        )
    messages = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(message.get("episode_id") != episode_id for message in messages):
        raise ValueError("messages.jsonl contains a different episode_id")
    message_ids = [str(message.get("msg_id", "")) for message in messages]
    if any(not message_id for message_id in message_ids):
        raise ValueError("messages.jsonl contains a message without msg_id")
    if len(message_ids) != len(set(message_ids)):
        raise ValueError("messages.jsonl contains duplicate msg_id values")
    return sorted(
        messages,
        key=lambda message: (
            int(message.get("step", 0)),
            _timestamp(message.get("timestamp")),
            str(message["msg_id"]),
        ),
    )


def _legacy_trajectory(
    episode_dir: Path,
    episode_id: str,
    agents: list[str],
    task_spec: str,
    outcome: dict[str, Any],
) -> Trajectory:
    messages = _load_legacy_messages(episode_dir, episode_id)
    message_by_id = {str(message["msg_id"]): message for message in messages}
    ordered: list[tuple[tuple[Any, ...], str, dict[str, Any]]] = []
    for message in messages:
        ordered.append((
            (
                int(message.get("step", 0)),
                _timestamp(message.get("timestamp")),
                1,
                str(message["msg_id"]),
            ),
            "message",
            message,
        ))

    trajectory_dir = episode_dir / "trajectories"
    trajectory_paths = sorted(trajectory_dir.glob("*.json"))
    if not trajectory_paths:
        raise LegacyEpisodeError(f"no agent trajectories found under {trajectory_dir}")
    for trajectory_path in trajectory_paths:
        agent_trajectory = AgentTrajectory.load(trajectory_path)
        if agent_trajectory.episode_id != episode_id:
            raise ValueError(f"trajectory contains a different episode_id: {trajectory_path}")
        for turn in agent_trajectory.turns:
            incoming = [
                message_by_id[message.msg_id]
                for message in turn.incoming_messages
                if message.msg_id in message_by_id
            ]
            outgoing = [
                message_by_id[message.msg_id]
                for message in turn.outgoing_messages
                if message.msg_id in message_by_id
            ]
            boundary = outgoing[0] if outgoing else (incoming[-1] if incoming else None)
            logical_step = int(
                (boundary or {}).get(
                    "step",
                    max(
                        [message.step for message in turn.incoming_messages]
                        + [message.step for message in turn.outgoing_messages]
                        + [0]
                    ),
                )
            )
            boundary_time = _timestamp((boundary or {}).get("timestamp"))
            rank = 0 if outgoing else 2
            for call_index, tool_call in enumerate(turn.tool_calls):
                ordered.append((
                    (
                        logical_step,
                        boundary_time,
                        rank,
                        agent_trajectory.agent,
                        turn.turn_id,
                        call_index,
                    ),
                    "tool",
                    {
                        "agent_id": agent_trajectory.agent,
                        "logical_step": logical_step,
                        "turn_id": turn.turn_id,
                        "call_index": call_index,
                        "name": tool_call.name,
                        "args": tool_call.args,
                        "result": tool_call.result,
                        "llm_call_index": tool_call.llm_call_index,
                    },
                ))

    steps: list[Message] = []
    for sequence, (_, kind, payload) in enumerate(sorted(ordered, key=lambda item: item[0]), 1):
        prefix = f"{episode_id}.legacy{sequence:06d}"
        if kind == "message":
            msg_type = str(payload.get("msg_type", ""))
            metadata = {
                "source_msg_id": payload["msg_id"],
                "source_msg_type": msg_type,
                "ordering": "legacy_message_log",
            }
            if payload.get("ticket_id") is not None:
                metadata["ticket_id"] = payload["ticket_id"]
            steps.append(Message(
                step_id=prefix,
                t=sequence * 2,
                sender=str(payload["sender"]),
                receiver=str(payload["receiver"]),
                channel=MESSAGE_CHANNELS.get(msg_type, "chat"),
                content=str(payload.get("content", "")),
                metadata=metadata,
            ))
            continue
        common_metadata = {
            "tool_id": str(payload["name"]),
            "logical_step": payload["logical_step"],
            "turn_id": payload["turn_id"],
            "llm_call_index": payload["llm_call_index"],
            "ordering": "legacy_agent_turn",
        }
        steps.extend([
            Message(
                step_id=f"{prefix}.call",
                t=sequence * 2,
                sender=str(payload["agent_id"]),
                receiver=f"tool:{payload['name']}",
                channel="tool_call",
                content=_canonical_content(payload["args"]),
                metadata=common_metadata,
            ),
            Message(
                step_id=f"{prefix}.result",
                t=sequence * 2 + 1,
                sender=f"tool:{payload['name']}",
                receiver=str(payload["agent_id"]),
                channel="tool_result",
                content=_canonical_content(payload["result"]),
                metadata=common_metadata,
            ),
        ])
    return Trajectory(
        episode_id=episode_id,
        agents=agents,
        task_spec=task_spec,
        steps=steps,
        outcome=outcome,
    )


def _canonical_content(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _message_from_bus_event(episode_id: str, event: dict[str, Any]) -> Message:
    payload = event["payload"]
    msg_type = str(payload.get("msg_type", ""))
    metadata = {
        "source_msg_id": payload.get("msg_id"),
        "source_msg_type": msg_type,
    }
    if payload.get("ticket_id") is not None:
        metadata["ticket_id"] = payload["ticket_id"]
    return Message(
        step_id=f"{episode_id}.e{event['event_seq']:06d}",
        t=event["event_seq"] * 2,
        sender=str(payload["sender"]),
        receiver=str(payload["receiver"]),
        channel=MESSAGE_CHANNELS.get(msg_type, "chat"),
        content=str(payload.get("content", "")),
        metadata=metadata,
    )


def _messages_from_tool_event(episode_id: str, event: dict[str, Any]) -> list[Message]:
    payload = event["payload"]
    agent_id = str(event["agent_id"])
    tool_id = str(payload["name"])
    prefix = f"{episode_id}.e{event['event_seq']:06d}"
    common_metadata = {
        "tool_id": tool_id,
        "logical_step": event.get("logical_step"),
        "llm_call_index": payload.get("llm_call_index"),
    }
    return [
        Message(
            step_id=f"{prefix}.call",
            t=event["event_seq"] * 2,
            sender=agent_id,
            receiver=f"tool:{tool_id}",
            channel="tool_call",
            content=_canonical_content(payload.get("args", {})),
            metadata=common_metadata,
        ),
        Message(
            step_id=f"{prefix}.result",
            t=event["event_seq"] * 2 + 1,
            sender=f"tool:{tool_id}",
            receiver=agent_id,
            channel="tool_result",
            content=_canonical_content(payload.get("result", {})),
            metadata=common_metadata,
        ),
    ]


def read_episode_trajectory(
    episode_dir: Path,
    episode_id: str,
    agents: list[str],
    task_spec: str,
    outcome: dict[str, Any],
) -> Trajectory:
    event_path = episode_dir / "events.jsonl"
    if not event_path.is_file():
        return _legacy_trajectory(
            episode_dir, episode_id, agents, task_spec, outcome
        )
    events = _load_events(event_path, episode_id)
    steps: list[Message] = []
    for event in events:
        if event["event_type"] == "message_published":
            steps.append(_message_from_bus_event(episode_id, event))
        elif event["event_type"] == "tool_call_completed":
            steps.extend(_messages_from_tool_event(episode_id, event))
    return Trajectory(
        episode_id=episode_id,
        agents=agents,
        task_spec=task_spec,
        steps=steps,
        outcome=outcome,
    )
