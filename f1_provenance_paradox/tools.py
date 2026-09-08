"""Legal-only policy knowledge-base search for F1."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from f1_provenance_paradox.ground_truth import LEGAL_AGENT, POLICY_FILES, load_artifact
from tools.registry import ToolRegistry

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "the", "to", "with",
}


@dataclass
class F1ToolContext:
    agent_name: str = ""
    policy_calls: list[dict[str, Any]] = field(default_factory=list)


def _chunks() -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    for filename in POLICY_FILES:
        document = load_artifact(filename)
        parts = re.split(r"(?=^## )", document, flags=re.MULTILINE)
        for index, part in enumerate(parts):
            text = part.strip()
            if text:
                chunks.append({
                    "chunk_id": f"{filename}:{index}",
                    "source": filename,
                    "text": text,
                })
    return chunks


def policy_kb_search(query: str, limit: int = 3) -> list[dict[str, str]]:
    query_tokens = {
        token for token in _TOKEN_RE.findall(query.casefold())
        if token not in _STOPWORDS
    }
    if not query_tokens:
        return []
    ranked: list[tuple[int, dict[str, str]]] = []
    for chunk in _chunks():
        text_tokens = set(_TOKEN_RE.findall(chunk["text"].casefold()))
        score = len(query_tokens & text_tokens)
        if score:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
    return [chunk for _, chunk in ranked[:max(1, min(limit, 5))]]


def _search_handler(ctx: F1ToolContext) -> Callable[..., dict[str, Any]]:
    def handler(query: str, step: int = 0, **_: Any) -> dict[str, Any]:
        chunks = policy_kb_search(query)
        ctx.policy_calls.append({
            "caller_agent": ctx.agent_name,
            "tool": "policy_kb_search",
            "query": query,
            "returned_chunks": chunks,
            "step": step,
        })
        return {"chunks": chunks}

    return handler


def build_f1_tool_registry(ctx: F1ToolContext, role: str) -> ToolRegistry:
    registry = ToolRegistry(ctx)  # type: ignore[arg-type]
    if role == LEGAL_AGENT:
        registry.register(
            "policy_kb_search",
            "Search current AcmeCorp internal policy documents for contract requirements.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Policy topic, clause, or control to retrieve.",
                    },
                },
                "required": ["query"],
            },
            _search_handler(ctx),
        )
    return registry