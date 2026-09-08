"""Host-only deterministic identity mapping."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SanitizeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sanitizer_version: str = Field(min_length=1)
    env_ids: dict[str, str] = Field(default_factory=dict)
    agent_ids: dict[str, str] = Field(default_factory=dict)
    tool_ids: dict[str, str] = Field(default_factory=dict)
    document_ids: dict[str, str] = Field(default_factory=dict)
    policy_ids: dict[str, str] = Field(default_factory=dict)
    episode_ids: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_bijections(self) -> "SanitizeManifest":
        for field_name in (
            "env_ids",
            "agent_ids",
            "tool_ids",
            "document_ids",
            "policy_ids",
            "episode_ids",
        ):
            mapping = getattr(self, field_name)
            if len(mapping.values()) != len(set(mapping.values())):
                raise ValueError(f"{field_name} must be one-to-one")
        return self