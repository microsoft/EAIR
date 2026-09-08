"""Deterministic interaction graph and structural lead annotations."""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
import os
from pathlib import Path
from typing import Any

import networkx as nx

from verifier.auditor_toolkit.bundle import Bundle


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
DEFAULT_EMBEDDING_MODEL_PATH = Path("/opt/models/all-MiniLM-L6-v2")


def edge_ref(sender: str, receiver: str, timestep: int) -> str:
    return f"{sender}->{receiver}@t{timestep}"


def _tokens(text: str) -> Counter[str]:
    return Counter(token.lower() for token in TOKEN_RE.findall(text))


def _character_ngrams(text: str, size: int = 3) -> Counter[str]:
    normalized = " ".join(text.casefold().split())
    return Counter(normalized[index:index + size] for index in range(len(normalized) - size + 1))


def _cosine(left_tokens: Counter[str], right_tokens: Counter[str]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    dot = sum(count * right_tokens[token] for token, count in left_tokens.items())
    left_norm = sum(count * count for count in left_tokens.values()) ** 0.5
    right_norm = sum(count * count for count in right_tokens.values()) ** 0.5
    return dot / (left_norm * right_norm)


def _lexical_similarity(left: str, right: str) -> float:
    word_similarity = _cosine(_tokens(left), _tokens(right))
    ngram_similarity = _cosine(_character_ngrams(left), _character_ngrams(right))
    return (word_similarity + ngram_similarity) / 2.0


@lru_cache(maxsize=1)
def _embedding_model():
    model_path = Path(os.environ.get(
        "VERIFIER_EMBEDDING_MODEL_PATH", str(DEFAULT_EMBEDDING_MODEL_PATH)
    ))
    if not model_path.is_dir():
        return None
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(str(model_path), local_files_only=True)


def _embedding_similarity(left: str, right: str) -> float | None:
    model = _embedding_model()
    if model is None:
        return None
    vectors = model.encode([left, right], normalize_embeddings=True)
    return float(sum(float(a) * float(b) for a, b in zip(vectors[0], vectors[1])))


@lru_cache(maxsize=4096)
def _similarity_components(left: str, right: str) -> tuple[float, float | None]:
    return _lexical_similarity(left, right), _embedding_similarity(left, right)


def _cosine_text(left: str, right: str) -> float:
    lexical, embedding = _similarity_components(left, right)
    return embedding if embedding is not None else lexical


def _summary(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _referenced_ids(step_data: dict[str, Any], key: str) -> set[str]:
    value = step_data.get("metadata", {}).get(key)
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    return set()


def build_interaction_graph(bundle: Bundle) -> dict[str, Any]:
    graph = nx.MultiDiGraph()
    role_by_id = {role.agent_id: role for role in bundle.metadata.roles}
    tool_by_id = {tool.tool_id: tool for tool in bundle.metadata.tools}

    for role in bundle.metadata.roles:
        graph.add_node(
            role.agent_id,
            kind="agent",
            title=role.title,
            seniority=role.seniority,
        )
    for tool in bundle.metadata.tools:
        graph.add_node(tool.tool_id, kind="tool", description=tool.description)
    for document in bundle.metadata.documents:
        graph.add_node(document.doc_id, kind="document", title=document.title)

    authority_edges: list[dict[str, str]] = []
    for role in bundle.metadata.roles:
        if role.reports_to:
            authority_edges.append({"subordinate": role.agent_id, "manager": role.reports_to})

    permission_flags: list[dict[str, Any]] = []
    consulted_policies: set[str] = set()
    consulted_documents: set[str] = set()
    interaction_edges: list[dict[str, Any]] = []
    provenance_chains: list[dict[str, Any]] = []
    information_steps = []
    chain_root_by_step: dict[str, Any] = {}

    for step in bundle.trajectory.steps:
        receiver = step.receiver.removeprefix("tool:")
        sender = step.sender
        if sender not in graph:
            graph.add_node(sender, kind="user" if sender.startswith("user:") else "external")
        if receiver not in graph:
            graph.add_node(receiver, kind="external")
        reference = edge_ref(sender, receiver, step.t)
        data = {
            "t": step.t,
            "channel": step.channel,
            "step_id": step.step_id,
            "edge_ref": reference,
            "summary": _summary(step.content),
        }
        graph.add_edge(sender, receiver, key=step.step_id, **data)
        interaction_edges.append({"source": sender, "target": receiver, **data})

        consulted_policies.update(_referenced_ids(step.model_dump(), "policy_id"))
        consulted_policies.update(_referenced_ids(step.model_dump(), "policy_ids"))
        consulted_documents.update(_referenced_ids(step.model_dump(), "doc_id"))
        consulted_documents.update(_referenced_ids(step.model_dump(), "doc_ids"))
        consulted_policies.update(
            policy.policy_id
            for policy in bundle.metadata.policies
            if policy.policy_id in step.content
        )
        consulted_documents.update(
            document.doc_id
            for document in bundle.metadata.documents
            if document.doc_id in step.content
        )
        if step.channel == "policy_check":
            consulted_policies.update(
                policy.policy_id
                for policy in bundle.metadata.policies
                if policy.policy_id in step.content
            )

        if step.channel == "tool_call" and sender in role_by_id and receiver in tool_by_id:
            role = role_by_id[sender]
            tool = tool_by_id[receiver]
            allowed = receiver in role.permissions or tool.permission_tag in role.permissions
            if not allowed:
                permission_flags.append({
                    "step_id": step.step_id,
                    "agent_id": sender,
                    "tool_id": receiver,
                    "edge_ref": reference,
                    "reason": "tool and permission tag are absent from role permissions",
                })

        if step.channel in {"handoff", "summary"}:
            relay_candidates = [
                candidate for candidate in information_steps
                if candidate.receiver.removeprefix("tool:") == step.sender
                and candidate.t < step.t
            ]
            if relay_candidates:
                source = max(
                    relay_candidates,
                    key=lambda candidate: _cosine_text(candidate.content, step.content),
                )
                root = chain_root_by_step.get(source.step_id, source)
                chain_root_by_step[step.step_id] = root
                lexical_similarity, embedding_similarity = _similarity_components(
                    root.content, step.content
                )
                similarity = (
                    embedding_similarity
                    if embedding_similarity is not None else lexical_similarity
                )
                provenance_chains.append({
                    "source_step_id": root.step_id,
                    "relay_step_id": source.step_id,
                    "downstream_step_id": step.step_id,
                    "edge_refs": [
                        edge_ref(root.sender, root.receiver.removeprefix("tool:"), root.t),
                        reference,
                    ],
                    "similarity": round(similarity, 6),
                    "semantic_divergence": round(1.0 - similarity, 6),
                    "embedding_similarity": (
                        round(embedding_similarity, 6)
                        if embedding_similarity is not None else None
                    ),
                    "lexical_similarity": round(lexical_similarity, 6),
                })
            information_steps.append(step)

    involved_roles = {
        participant
        for step in bundle.trajectory.steps
        for participant in (step.sender, step.receiver)
        if participant in role_by_id
    }
    unconsulted_obligations = [
        {
            "kind": "policy",
            "id": policy.policy_id,
            "applicable_agents": sorted(set(policy.applies_to) & involved_roles),
        }
        for policy in bundle.metadata.policies
        if set(policy.applies_to) & involved_roles and policy.policy_id not in consulted_policies
    ]
    unconsulted_obligations.extend(
        {
            "kind": "document",
            "id": document.doc_id,
            "applicable_agents": sorted(set(document.acl) & involved_roles),
        }
        for document in bundle.metadata.documents
        if set(document.acl) & involved_roles and document.doc_id not in consulted_documents
    )

    node_link = nx.node_link_data(graph, edges="edges")
    node_link["edges"] = sorted(
        node_link["edges"], key=lambda item: (item["t"], item["step_id"])
    )
    return {
        "schema_version": "1.0",
        "bundle": bundle.as_summary(),
        "graph": node_link,
        "interaction_edges": interaction_edges,
        "annotations": {
            "authority_edges": authority_edges,
            "permission_violation_flags": permission_flags,
            "provenance_chains": provenance_chains,
            "unconsulted_obligations": unconsulted_obligations,
        },
    }


def trace_provenance(graph_data: dict[str, Any], step_id: str) -> list[dict[str, Any]]:
    chains = graph_data["annotations"]["provenance_chains"]
    return [
        chain for chain in chains
        if step_id in {chain["source_step_id"], chain["downstream_step_id"]}
    ]


def diff_summary(bundle: Bundle, source_step_id: str, summary_step_id: str) -> dict[str, Any]:
    steps = {step.step_id: step for step in bundle.trajectory.steps}
    if source_step_id not in steps or summary_step_id not in steps:
        missing = {source_step_id, summary_step_id} - set(steps)
        raise KeyError(f"unknown step(s): {sorted(missing)}")
    source = steps[source_step_id]
    summary = steps[summary_step_id]
    source_tokens = set(_tokens(source.content))
    summary_tokens = set(_tokens(summary.content))
    lexical_similarity, embedding_similarity = _similarity_components(
        source.content, summary.content
    )
    similarity = (
        embedding_similarity
        if embedding_similarity is not None else lexical_similarity
    )
    return {
        "source_step_id": source_step_id,
        "summary_step_id": summary_step_id,
        "similarity": round(similarity, 6),
        "semantic_divergence": round(1.0 - similarity, 6),
        "embedding_similarity": (
            round(embedding_similarity, 6)
            if embedding_similarity is not None else None
        ),
        "lexical_similarity": round(lexical_similarity, 6),
        "source_only_tokens": sorted(source_tokens - summary_tokens),
        "summary_only_tokens": sorted(summary_tokens - source_tokens),
        "source_content": source.content,
        "summary_content": summary.content,
    }


def check_permission(bundle: Bundle, agent_id: str, action: str) -> dict[str, Any]:
    roles = {role.agent_id: role for role in bundle.metadata.roles}
    if agent_id not in roles:
        raise KeyError(f"unknown agent: {agent_id}")
    role = roles[agent_id]
    tool = next((tool for tool in bundle.metadata.tools if tool.tool_id == action), None)
    allowed = action in role.permissions or (
        tool is not None and tool.permission_tag in role.permissions
    )
    return {
        "agent_id": agent_id,
        "action": action,
        "allowed": allowed,
        "declared_permissions": role.permissions,
        "matched_permission_tag": tool.permission_tag if tool and tool.permission_tag in role.permissions else None,
    }


def graph_query(graph_data: dict[str, Any], pattern: str) -> list[dict[str, Any]]:
    normalized = pattern.casefold().strip()
    edges = graph_data["interaction_edges"]
    if normalized == "permission violations":
        return graph_data["annotations"]["permission_violation_flags"]
    if normalized == "unconsulted obligations":
        return graph_data["annotations"]["unconsulted_obligations"]
    if normalized == "approval decisions":
        return [edge for edge in edges if edge["channel"] == "approval_decision"]
    if normalized == "summaries":
        return [edge for edge in edges if edge["channel"] == "summary"]
    if normalized.startswith("channel="):
        channel = normalized.partition("=")[2]
        return [edge for edge in edges if edge["channel"] == channel]
    raise ValueError(
        "unsupported graph query; use permission violations, unconsulted obligations, "
        "approval decisions, summaries, or channel=<channel>"
    )
