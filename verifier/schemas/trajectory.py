"""Environment-neutral execution trajectory schema."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Channel = Literal[
    "handoff",
    "approval_request",
    "approval_decision",
    "summary",
    "tool_call",
    "tool_result",
    "policy_check",
    "chat",
]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    t: int = Field(ge=0)
    sender: str = Field(min_length=1)
    receiver: str = Field(min_length=1)
    channel: Channel
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Trajectory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: str = Field(min_length=1)
    agents: list[str]
    task_spec: str = Field(min_length=1)
    steps: list[Message]
    outcome: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_identity_and_order(self) -> "Trajectory":
        if len(self.agents) != len(set(self.agents)):
            raise ValueError("trajectory agents must be unique")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("trajectory step_ids must be globally unique")
        timesteps = [step.t for step in self.steps]
        if timesteps != sorted(timesteps):
            raise ValueError("trajectory steps must be ordered by timestep")
        return self
