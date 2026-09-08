"""Base agent with memory, tool-use loop, and trajectory saving."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agents.memory import (
    LLMCallRecord,
    MemoryItem,
    MessageMemoryItem,
    NoteRecord,
    ToolCallRecord,
    ToolMemoryItem,
    Trajectory,
    TurnRecord,
)
from comms.events import get_event_recorder
from comms.schema import Message
from llm.client import LLMClient, LLMResponse, ToolCall
from tools.registry import ToolRegistry


class BaseAgent:
    """LLM agent with private memory, tool-use act loop, and trajectory logging."""

    def __init__(
        self,
        name: str,
        episode_id: str,
        system_prompt: str,
        llm: LLMClient,
        tools: ToolRegistry,
        temperature: float = 0.7,
        max_tool_calls_per_turn: int = 8,
        tool_choice: str | None = None,
    ) -> None:
        self.name = name
        self.episode_id = episode_id
        self.system_prompt = system_prompt
        self.llm = llm
        self.tools = tools
        self.temperature = temperature
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        # If set (e.g. "required"), forces a tool call on the FIRST LLM call
        # of each turn only — later calls in the same turn stay "auto" so the
        # model can still stop after it has called what it needed to call.
        # Default None preserves prior behavior for callers that don't set it.
        self.tool_choice = tool_choice
        self.memory: list[MemoryItem] = []
        self.trajectory = Trajectory(
            agent=name,
            episode_id=episode_id,
            system_prompt=system_prompt,
        )
        self._turn_counter = 0
        self._pending_outgoing: list[Message] = []

    def receive_message(self, msg: Message) -> None:
        """Deliver a message into private memory."""
        if msg.sender != self.name and msg.receiver != self.name:
            return
        existing_ids = {
            item.message.msg_id
            for item in self.memory
            if isinstance(item, MessageMemoryItem)
        }
        if msg.msg_id not in existing_ids:
            self.memory.insert(0, MessageMemoryItem(message=msg))

    def append_note(self, text: str, step: int = 0) -> dict[str, Any]:
        """Add a scratchpad note to memory."""
        self.memory.insert(0, NoteRecord(text=text, step=step))
        return {"status": "ok", "note": text}

    def record_outgoing(self, msg: Message) -> None:
        """Track outgoing messages for the current turn."""
        self._pending_outgoing.append(msg)

    def _serialize_memory(self) -> list[dict[str, Any]]:
        """Serialize memory for LLM context (most recent first)."""
        items: list[dict[str, Any]] = []
        for item in self.memory:
            if isinstance(item, MessageMemoryItem):
                m = item.message
                items.append({
                    "type": "message",
                    "sender": m.sender,
                    "receiver": m.receiver,
                    "msg_type": m.msg_type,
                    "content": m.content,
                    "step": m.step,
                })
            elif isinstance(item, ToolMemoryItem):
                tc = item.tool_call
                items.append({
                    "type": "tool",
                    "name": tc.name,
                    "args": tc.args,
                    "result": tc.result,
                })
            elif isinstance(item, NoteRecord):
                items.append({"type": "note", "text": item.text})
        return items

    def _build_messages(self, instruction: str) -> list[dict[str, Any]]:
        """Build LLM chat messages from prompt, instruction, and memory."""
        memory_text = json.dumps(self._serialize_memory(), indent=2)
        return [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    f"INSTRUCTION: {instruction}\n\n"
                    f"YOUR MEMORY (most recent first):\n{memory_text}"
                ),
            },
        ]

    def act(
        self,
        instruction: str,
        incoming_messages: list[Message] | None = None,
        step: int = 0,
    ) -> list[Message]:
        """Run tool-use loop for one turn; return outgoing messages."""
        if incoming_messages:
            for msg in incoming_messages:
                self.receive_message(msg)

        turn = TurnRecord(
            turn_id=self._turn_counter,
            instruction=instruction,
            incoming_messages=incoming_messages or [],
        )
        self._turn_counter += 1
        self._pending_outgoing = []
        recorder = get_event_recorder(self.episode_id)
        if recorder is not None:
            recorder.append(
                "turn_started",
                agent_id=self.name,
                logical_step=step,
                payload={"turn_id": turn.turn_id, "instruction": instruction},
            )

        messages = self._build_messages(instruction)
        tool_schemas = self.tools.get_schemas()
        tool_calls_made = 0
        finalization_turn: TurnRecord | None = None

        while tool_calls_made < self.max_tool_calls_per_turn:
            response = self.llm.chat(
                messages=messages,
                tools=tool_schemas,
                temperature=self.temperature,
                tool_choice=self.tool_choice if tool_calls_made == 0 else None,
            )
            turn.llm_calls.append(
                LLMCallRecord(
                    request_messages=list(messages),
                    response=response.raw,
                )
            )
            if recorder is not None:
                recorder.append(
                    "llm_call_completed",
                    agent_id=self.name,
                    logical_step=step,
                    payload={
                        "turn_id": turn.turn_id,
                        "llm_call_index": len(turn.llm_calls) - 1,
                        "request_messages": list(messages),
                        "response": response.raw,
                    },
                )

            if not response.tool_calls:
                if response.content:
                    self._handle_text_reply(response.content, step)
                break

            for tc in response.tool_calls:
                if tool_calls_made >= self.max_tool_calls_per_turn:
                    break
                result = self.tools.execute(self.name, tc.name, tc.arguments, step)
                record = ToolCallRecord(
                    name=tc.name,
                    args=tc.arguments,
                    result=result,
                    llm_call_index=len(turn.llm_calls) - 1,
                )
                turn.tool_calls.append(record)
                if recorder is not None:
                    recorder.append(
                        "tool_call_completed",
                        agent_id=self.name,
                        logical_step=step,
                        payload=record.model_dump(mode="json"),
                    )
                self.memory.insert(0, ToolMemoryItem(tool_call=record))
                tool_calls_made += 1

                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

        if tool_calls_made >= self.max_tool_calls_per_turn:
            final_messages = self._build_messages(instruction)
            finalization_instruction = (
                "The tool-call allowance for this turn is exhausted. "
                "Using the tool results now present in your memory, return "
                "the complete final response now without calling more tools."
            )
            final_messages.append({
                "role": "user",
                "content": finalization_instruction,
            })
            response = self.llm.chat(
                messages=final_messages,
                tools=[],
                temperature=self.temperature,
            )
            finalization_turn = TurnRecord(
                turn_id=self._turn_counter,
                instruction=finalization_instruction,
                incoming_messages=[],
            )
            self._turn_counter += 1
            finalization_turn.llm_calls.append(
                LLMCallRecord(
                    request_messages=list(final_messages),
                    response=response.raw,
                )
            )
            if recorder is not None:
                recorder.append(
                    "llm_call_completed",
                    agent_id=self.name,
                    logical_step=step,
                    payload={
                        "turn_id": finalization_turn.turn_id,
                        "llm_call_index": 0,
                        "request_messages": list(final_messages),
                        "response": response.raw,
                        "finalization": True,
                    },
                )
            if response.content:
                self._handle_text_reply(response.content, step)

        turn.outgoing_messages = list(self._pending_outgoing)
        turn.memory_snapshot_len = len(self.memory)
        self.trajectory.turns.append(turn)
        if finalization_turn is not None:
            finalization_turn.memory_snapshot_len = len(self.memory)
            self.trajectory.turns.append(finalization_turn)
        if recorder is not None:
            recorder.append(
                "turn_completed",
                agent_id=self.name,
                logical_step=step,
                payload={
                    "turn_id": turn.turn_id,
                    "outgoing_message_ids": [message.msg_id for message in turn.outgoing_messages],
                },
            )
        return turn.outgoing_messages

    def _handle_text_reply(self, content: str, step: int) -> None:
        """Default handler for plain-text replies (overridden by orchestrator hooks)."""
        pass

    def save_trajectory(self, episode_dir: Path) -> Path:
        """Persist trajectory JSON."""
        traj_dir = episode_dir / "trajectories"
        traj_dir.mkdir(parents=True, exist_ok=True)
        self.trajectory.final_memory = self._serialize_memory()
        path = traj_dir / f"{self.name}.json"
        self.trajectory.save(path)
        return path

    def reconstruct_context(self, turn_id: int | None = None) -> dict[str, Any]:
        """Reconstruct full agent context from trajectory (for tests)."""
        if turn_id is not None:
            turn = self.trajectory.turns[turn_id]
            return {
                "system_prompt": self.system_prompt,
                "instruction": turn.instruction,
                "memory": turn.memory_snapshot_len,
                "llm_calls": [c.model_dump() for c in turn.llm_calls],
            }
        return {
            "system_prompt": self.system_prompt,
            "final_memory": self.trajectory.final_memory,
            "turns": len(self.trajectory.turns),
        }
