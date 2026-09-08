"""Closed vocabulary of coder intervention operators."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OperatorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddApprovalGate(OperatorParams):
    edge: str
    approver_role: str
    condition: str


class RemoveHandoffEdge(OperatorParams):
    edge: str


class AddHandoffEdge(OperatorParams):
    src: str
    dst: str


class RerouteInformation(OperatorParams):
    from_edge: str
    via_role: str


class AddCrossCheck(OperatorParams):
    stage: str
    checker_role: str


class PatchRolePrompt(OperatorParams):
    agent_id: str
    patch_type: Literal[
        "append_policy_reminder",
        "add_skepticism_clause",
        "clarify_authority_scope",
        "add_kpi_guardrail",
    ]
    text: str = Field(min_length=1)


class RewriteRolePrompt(OperatorParams):
    agent_id: str
    new_prompt: str = Field(min_length=1)


class RestrictTool(OperatorParams):
    agent_id: str
    tool_id: str


class GrantTool(OperatorParams):
    agent_id: str
    tool_id: str


class EnforceMessageSchema(OperatorParams):
    channel: str
    schema_: dict[str, Any] = Field(alias="schema")


class SetMemoryPolicy(OperatorParams):
    agent_id: str
    policy: dict[str, Any] | str


class SetGateParam(OperatorParams):
    gate_id: str
    key: str
    value: Any


OPERATOR_MODELS: dict[str, type[OperatorParams]] = {
    "add_approval_gate": AddApprovalGate,
    "remove_handoff_edge": RemoveHandoffEdge,
    "add_handoff_edge": AddHandoffEdge,
    "reroute_information": RerouteInformation,
    "add_cross_check": AddCrossCheck,
    "patch_role_prompt": PatchRolePrompt,
    "rewrite_role_prompt": RewriteRolePrompt,
    "restrict_tool": RestrictTool,
    "grant_tool": GrantTool,
    "enforce_message_schema": EnforceMessageSchema,
    "set_memory_policy": SetMemoryPolicy,
    "set_gate_param": SetGateParam,
}


def validate_operator_params(operator: str, params: dict[str, Any]) -> OperatorParams:
    try:
        model = OPERATOR_MODELS[operator]
    except KeyError as exc:
        choices = ", ".join(OPERATOR_MODELS)
        raise ValueError(f"unknown operator '{operator}'; choose from: {choices}") from exc
    return model.model_validate(params)
