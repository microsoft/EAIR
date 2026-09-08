"""Agent memory items and trajectory schemas."""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from comms.schema import Message


class ToolCallRecord(BaseModel):
    """Record of a tool invocation and its result."""

    name: str
    args: dict[str, Any]
    result: dict[str, Any]
    llm_call_index: int | None = None


class NoteRecord(BaseModel):
    """Self-written scratchpad note."""

    type: Literal["note"] = "note"
    text: str
    step: int


class MessageMemoryItem(BaseModel):
    """Message stored in agent memory."""

    type: Literal["message"] = "message"
    message: Message


class ToolMemoryItem(BaseModel):
    """Tool call stored in agent memory."""

    type: Literal["tool"] = "tool"
    tool_call: ToolCallRecord


MemoryItem = Union[MessageMemoryItem, ToolMemoryItem, NoteRecord]


class LLMCallRecord(BaseModel):
    """Full LLM request/response for trajectory logging."""

    request_messages: list[dict[str, Any]]
    response: dict[str, Any]


class TurnRecord(BaseModel):
    """One agent turn within an episode."""

    turn_id: int
    instruction: str
    incoming_messages: list[Message]
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    outgoing_messages: list[Message] = Field(default_factory=list)
    memory_snapshot_len: int = 0


class Trajectory(BaseModel):
    """Complete agent trajectory for an episode."""

    agent: str
    episode_id: str
    system_prompt: str
    turns: list[TurnRecord] = Field(default_factory=list)
    final_memory: list[dict[str, Any]] = Field(default_factory=list)

    def save(self, path: str | Any) -> None:
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Any) -> Trajectory:
        from pathlib import Path

        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
