"""Episode-scoped message bus with JSONL logging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from comms.events import register_event_recorder
from comms.schema import Message

if TYPE_CHECKING:
    from agents.base import BaseAgent


class MessageBus:
    """Append-only message log with delivery to registered agents."""

    def __init__(self, episode_dir: Path, episode_id: str) -> None:
        self.episode_id = episode_id
        self.episode_dir = episode_dir
        self.log_path = episode_dir / "messages.jsonl"
        self.event_recorder = register_event_recorder(episode_id, episode_dir)
        self._agents: dict[str, BaseAgent] = {}
        self._step = 0
        self.episode_dir.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch()

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        """Register an agent to receive delivered messages."""
        self._agents[name] = agent

    @property
    def step(self) -> int:
        return self._step

    def advance_step(self) -> int:
        """Increment and return the global step counter."""
        self._step += 1
        return self._step

    def publish(
        self,
        sender: str,
        receiver: str,
        msg_type: str,
        content: str,
        ticket_id: str | None = None,
        step: int | None = None,
    ) -> Message:
        """Create, log, and deliver a message."""
        if step is None:
            step = self._step
        msg = Message(
            episode_id=self.episode_id,
            ticket_id=ticket_id,
            step=step,
            sender=sender,
            receiver=receiver,
            msg_type=msg_type,  # type: ignore[arg-type]
            content=content,
        )
        self._append_log(msg)
        self._deliver(msg)
        return msg

    def republish(self, msg: Message) -> Message:
        """Log and deliver an existing message object."""
        self._append_log(msg)
        self._deliver(msg)
        return msg

    def _append_log(self, msg: Message) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(msg.model_dump_json() + "\n")
        self.event_recorder.append(
            "message_published",
            agent_id=str(msg.sender),
            logical_step=msg.step,
            payload=msg.model_dump(mode="json"),
        )

    def _deliver(self, msg: Message) -> None:
        receiver = self._agents.get(str(msg.receiver))
        if receiver is not None:
            receiver.receive_message(msg)
        sender = self._agents.get(str(msg.sender))
        if sender is not None and str(msg.sender) != str(msg.receiver):
            sender.receive_message(msg)

    def read_all(self) -> list[Message]:
        """Read all messages from the JSONL log."""
        if not self.log_path.exists():
            return []
        messages: list[Message] = []
        with self.log_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    messages.append(Message.model_validate_json(line))
        return messages
