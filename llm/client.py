"""Provider-agnostic LLM client for Anthropic and OpenAI."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    """Normalized tool call from an LLM response."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Normalized LLM response."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMBackend(Protocol):
    """Protocol for LLM provider backends."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse: ...


class MockLLMBackend:
    """Deterministic mock backend for tests and smoke runs."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_index = 0
        self.call_log: list[dict[str, Any]] = []

    def add_response(self, response: LLMResponse) -> None:
        self._responses.append(response)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.call_log.append({
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "tool_choice": tool_choice,
            "response_format": response_format,
        })
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
            self._call_index += 1
            return resp
        return LLMResponse(content="I have completed my task.", raw={"mock": True})


class OpenAIBackend:
    """OpenAI chat completions with tool calling."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        from openai import OpenAI

        is_grok = model.lower().startswith("grok-")
        self.client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url,
            max_retries=int(os.environ.get(
                "OPENAI_MAX_RETRIES", "0" if is_grok else "6"
            )),
            timeout=float(os.environ.get(
                "OPENAI_REQUEST_TIMEOUT", "90" if is_grok else "180"
            )),
        )
        self.model = model
        self.max_transient_attempts = int(os.environ.get(
            "OPENAI_TRANSIENT_MAX_ATTEMPTS", "12" if is_grok else "60"
        ))

    def _create_with_retry(self, **kwargs):
        """Call chat.completions.create with backoff on transient errors.

        TRAPI can return sustained 429s, so retry many times with gentle,
        capped waits (roughly a 10-minute resilience window).
        """
        from openai import (
            APIConnectionError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        )

        for attempt in range(self.max_transient_attempts):
            try:
                return self.client.chat.completions.create(**kwargs)
            except (
                RateLimitError,
                APIConnectionError,
                APITimeoutError,
                InternalServerError,
            ):
                if attempt == self.max_transient_attempts - 1:
                    raise
                delay = min(2.0 + attempt * 1.5, 15.0) + random.uniform(0, 1.0)
                time.sleep(delay)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            if self.model.startswith("Llama-"):
                kwargs["parallel_tool_calls"] = False
            if tool_choice == "required":
                kwargs["tool_choice"] = "required"
            elif tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        if response_format is not None:
            kwargs["response_format"] = response_format
        if extra_body:
            kwargs.update(extra_body)
        resp = self._create_with_retry(**kwargs)
        choice = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                arguments, _ = json.JSONDecoder().raw_decode(
                    tc.function.arguments.lstrip()
                )
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                ))
        return LLMResponse(
            content=choice.content,
            tool_calls=tool_calls,
            raw=resp.model_dump(),
        )


class AnthropicBackend:
    """Anthropic messages API with tool calling."""

    def __init__(self, model: str) -> None:
        from anthropic import Anthropic

        self.client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        # response_format has no Anthropic Messages API equivalent here; ignored.
        system = ""
        api_messages: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                api_messages.append(m)

        anthropic_tools = None
        if tools:
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", t)
                anthropic_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system,
            "messages": api_messages,
            "temperature": temperature,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
            if tool_choice == "required":
                kwargs["tool_choice"] = {"type": "any"}
            elif isinstance(tool_choice, dict):
                kwargs["tool_choice"] = tool_choice

        resp = self.client.messages.create(**kwargs)
        content_text = ""
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))

        return LLMResponse(
            content=content_text or None,
            tool_calls=tool_calls,
            raw=resp.model_dump(),
        )


class OpenRouterBackend(OpenAIBackend):
    """OpenRouter via OpenAI-compatible API."""

    def __init__(self, model: str) -> None:
        super().__init__(
            model=model,
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        )


def _restore_llama_tool_arguments(
    action: str,
    target: str,
    content: str,
    tool_schemas: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Restore arguments from TRAPI Llama's generic use_tool envelope."""
    try:
        decoded = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        decoded = None
    if isinstance(decoded, dict):
        return decoded

    if action == "read_logs":
        return {"source": target}
    if action == "read_document":
        return {"name": target}
    if action == "submit_report_section":
        return {"field": target, "content": content}
    properties = tool_schemas.get(action, {}).get("properties", {})
    if len(properties) == 1:
        return {next(iter(properties)): content}
    return {"content": content}


class TRAPIBackend(OpenAIBackend):
    """Azure OpenAI via the TRAPI endpoint with Microsoft Entra ID auth.

    Uses a bearer-token provider (a callable) as the API key so tokens are
    refreshed automatically per request. Authentication chains the Azure CLI
    credential and a managed identity credential.
    """

    def __init__(self, model: str) -> None:
        from azure.identity import (
            AzureCliCredential,
            ChainedTokenCredential,
            ManagedIdentityCredential,
            get_bearer_token_provider,
        )

        scope = os.environ.get("TRAPI_SCOPE", "api://trapi/.default")
        host = os.environ.get("TRAPI_HOST", "https://trapi.research.microsoft.com")
        endpoint = os.environ.get(
            "OPENAI_BASE_URL", f"{host}/redmond/interactive/openai/v1"
        )
        token_provider = get_bearer_token_provider(
            ChainedTokenCredential(AzureCliCredential(), ManagedIdentityCredential()),
            scope,
        )
        super().__init__(
            model=model,
            api_key=token_provider,  # callable, auto-refreshes per request
            base_url=endpoint,
        )
        self._response_batches: dict[str, tuple[str, list[dict[str, Any]]]] = {}

    def _responses_input(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        instructions: list[str] = []
        response_input: list[dict[str, Any]] = []
        restored_batches: set[str] = set()
        batches = getattr(self, "_response_batches", {})
        for message in messages:
            role = message["role"]
            if role == "system":
                instructions.append(message.get("content", ""))
                continue
            if role == "tool":
                response_input.append({
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message.get("content", ""),
                })
                continue
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                for tool_call in tool_calls:
                    call_id = tool_call["id"]
                    batch = batches.get(call_id)
                    if batch and batch[0] not in restored_batches:
                        response_input.extend(batch[1])
                        restored_batches.add(batch[0])
                    elif not batch:
                        function = tool_call["function"]
                        response_input.append({
                            "type": "function_call",
                            "call_id": call_id,
                            "name": function["name"],
                            "arguments": function.get("arguments", "{}"),
                        })
                if message.get("content"):
                    response_input.append({
                        "role": "assistant",
                        "content": message["content"],
                    })
                continue
            response_input.append({
                "role": role,
                "content": message.get("content", ""),
            })
        return "\n\n".join(instructions), response_input

    def _chat_responses(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        response_format: dict[str, Any] | None,
    ) -> LLMResponse:
        instructions, response_input = self._responses_input(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": response_input,
        }
        if tools:
            kwargs["tools"] = [{
                "type": "function",
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "parameters": tool["function"].get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            } for tool in tools]
            kwargs["parallel_tool_calls"] = False
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        if response_format is not None:
            kwargs["text"] = {"format": response_format}
        response = self.client.responses.create(**kwargs)
        output_items = []
        for item in response.output:
            output_item = item.model_dump()
            output_item.pop("status", None)
            output_items.append(output_item)
        tool_calls: list[ToolCall] = []
        for item in response.output:
            if item.type != "function_call":
                continue
            arguments, _ = json.JSONDecoder().raw_decode(item.arguments.lstrip())
            tool_calls.append(ToolCall(
                id=item.call_id,
                name=item.name,
                arguments=arguments,
            ))
            self._response_batches[item.call_id] = (response.id, output_items)
        return LLMResponse(
            content=response.output_text or None,
            tool_calls=tool_calls,
            raw=response.model_dump(),
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        # This TRAPI model only supports the default temperature (1).
        if self.model.startswith("gpt-5.6-terra"):
            return self._chat_responses(
                messages, tools, tool_choice, response_format
            )
        if tools and self.model.startswith("Llama-"):
            original_tool_names = {
                tool["function"]["name"] for tool in tools
            }
            original_tool_schemas = {
                tool["function"]["name"]: tool["function"].get("parameters", {})
                for tool in tools
            }
            messages = json.loads(json.dumps(messages))
            messages[0]["content"] += (
                "\n\nTOOL-CALL PROTOCOL: Call exactly one tool per response. "
                "After receiving that tool's result, you may call one more tool "
                "in your next response. Never emit multiple tool calls together. "
                "Set action to the tool name and set content to a JSON-encoded "
                "object containing all arguments required by that tool's schema."
            )
            for message in messages:
                for tool_call in message.get("tool_calls", []):
                    function = tool_call.get("function", {})
                    if function.get("name") not in original_tool_names:
                        continue
                    arguments = json.loads(function.get("arguments", "{}"))
                    function["arguments"] = json.dumps({
                        "action": function["name"],
                        "target": "",
                        "content": json.dumps(arguments),
                    })
                    function["name"] = "use_tool"
            schema_guide = json.dumps(original_tool_schemas, separators=(",", ":"))
            tools = [{
                "type": "function",
                "function": {
                    "name": "use_tool",
                    "description": (
                        "Call one available action. content MUST be a JSON-encoded "
                        "object satisfying the selected action's parameter schema. "
                        f"Action schemas: {schema_guide}"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": sorted(original_tool_names),
                            },
                            "target": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["action", "target", "content"],
                    },
                },
            }]
            response = super().chat(
                messages,
                tools,
                1.0,
                tool_choice=tool_choice,
                response_format=response_format,
            )
            restored_calls = []
            for tool_call in response.tool_calls:
                if tool_call.name != "use_tool":
                    restored_calls.append(tool_call)
                    continue
                arguments = dict(tool_call.arguments)
                action = arguments.pop("action", "")
                if action in original_tool_names:
                    target = arguments.get("target", "")
                    restored_arguments = _restore_llama_tool_arguments(
                        action,
                        target,
                        arguments.get("content", ""),
                        original_tool_schemas,
                    )
                    restored_calls.append(ToolCall(
                        id=tool_call.id,
                        name=action,
                        arguments=restored_arguments,
                    ))
            response.tool_calls = restored_calls
            return response
        return super().chat(
            messages,
            tools,
            1.0,
            tool_choice=tool_choice,
            response_format=response_format,
        )


class LLMClient:
    """Thin wrapper selecting backend by provider name."""

    def __init__(
        self,
        provider: str = "mock",
        model: str = "gpt-4o-mini",
        backend: LLMBackend | None = None,
    ) -> None:
        if backend is not None:
            self._backend = backend
        elif provider == "openai":
            self._backend = OpenAIBackend(model)
        elif provider == "openrouter":
            self._backend = OpenRouterBackend(model)
        elif provider == "trapi":
            self._backend = TRAPIBackend(model)
        elif provider == "anthropic":
            self._backend = AnthropicBackend(model)
        else:
            self._backend = MockLLMBackend()

    @property
    def backend(self) -> LLMBackend:
        return self._backend

    def effective_sampling_parameters(
        self,
        temperature: float,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Report sampling parameters actually supported by the selected backend."""
        if type(self._backend) in (OpenAIBackend, OpenRouterBackend):
            return {"temperature": temperature, "seed": seed}
        if isinstance(self._backend, TRAPIBackend):
            return {"temperature": 1.0, "seed": None}
        return {"temperature": temperature, "seed": None}

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> LLMResponse:
        if type(self._backend) in (OpenAIBackend, OpenRouterBackend):
            return self._backend.chat(
                messages,
                tools,
                temperature,
                tool_choice=tool_choice,
                response_format=response_format,
                extra_body={"seed": seed} if seed is not None else None,
            )
        return self._backend.chat(
            messages, tools, temperature,
            tool_choice=tool_choice, response_format=response_format,
        )
