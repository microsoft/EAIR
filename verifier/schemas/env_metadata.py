"""Complete, identity-sanitized environment metadata schema."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Role(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    seniority: str | None = None
    system_prompt: str = Field(min_length=1)
    permissions: list[str] = Field(default_factory=list)
    reports_to: str | None = None


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    applies_to: list[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    permission_tag: str = Field(min_length=1)


class DocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    acl: list[str] = Field(default_factory=list)
    path: str = Field(min_length=1)


class EnvMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    env_ref: str = Field(min_length=1)
    description: str = Field(min_length=1)
    roles: list[Role]
    policies: list[Policy]
    workflow: dict[str, Any]
    tools: list[ToolSpec]
    documents: list[DocumentRef]
    harness: dict[str, Any]

    @model_validator(mode="after")
    def validate_inventory(self) -> "EnvMetadata":
        inventories = {
            "role agent_id": [role.agent_id for role in self.roles],
            "policy policy_id": [policy.policy_id for policy in self.policies],
            "tool tool_id": [tool.tool_id for tool in self.tools],
            "document doc_id": [document.doc_id for document in self.documents],
            "document path": [document.path for document in self.documents],
        }
        for name, values in inventories.items():
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name}")

        role_ids = set(inventories["role agent_id"])
        for role in self.roles:
            if role.reports_to is not None and role.reports_to not in role_ids:
                raise ValueError(f"unresolved reports_to role: {role.reports_to}")
        for policy in self.policies:
            unresolved = set(policy.applies_to) - role_ids
            if unresolved:
                raise ValueError(f"policy has unresolved roles: {sorted(unresolved)}")
        for document in self.documents:
            unresolved = set(document.acl) - role_ids
            if unresolved:
                raise ValueError(f"document has unresolved ACL roles: {sorted(unresolved)}")
        return self
