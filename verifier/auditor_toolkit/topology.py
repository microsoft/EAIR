"""Topology-only navigation with raw trajectory references and no risk annotations."""

from __future__ import annotations

from typing import Any

import networkx as nx

from verifier.auditor_toolkit.bundle import Bundle
from verifier.auditor_toolkit.graph import edge_ref


def build_interaction_graph(bundle: Bundle) -> dict[str, Any]:
    graph = nx.MultiDiGraph()
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

    interaction_edges = []
    for step in bundle.trajectory.steps:
        receiver = step.receiver.removeprefix("tool:")
        sender = step.sender
        if sender not in graph:
            graph.add_node(
                sender, kind="user" if sender.startswith("user:") else "external"
            )
        if receiver not in graph:
            graph.add_node(receiver, kind="external")
        reference = edge_ref(sender, receiver, step.t)
        data = {
            "t": step.t,
            "channel": step.channel,
            "step_id": step.step_id,
            "edge_ref": reference,
        }
        graph.add_edge(sender, receiver, key=step.step_id, **data)
        interaction_edges.append({"source": sender, "target": receiver, **data})

    node_link = nx.node_link_data(graph, edges="edges")
    node_link["edges"] = sorted(
        node_link["edges"], key=lambda item: (item["t"], item["step_id"])
    )
    return {
        "schema_version": "topology-1.0",
        "bundle": bundle.as_summary(),
        "graph": node_link,
        "interaction_edges": interaction_edges,
    }


def trace_provenance(graph_data: dict[str, Any], step_id: str) -> list[dict[str, Any]]:
    raise ValueError("provenance annotations are unavailable in topology-only mode")


def graph_query(graph_data: dict[str, Any], pattern: str) -> list[dict[str, Any]]:
    normalized = pattern.casefold().strip()
    edges = graph_data["interaction_edges"]
    if normalized == "approval decisions":
        return [edge for edge in edges if edge["channel"] == "approval_decision"]
    if normalized == "summaries":
        return [edge for edge in edges if edge["channel"] == "summary"]
    if normalized.startswith("channel="):
        channel = normalized.partition("=")[2]
        return [edge for edge in edges if edge["channel"] == channel]
    raise ValueError(
        "unsupported topology query; use approval decisions, summaries, or "
        "channel=<channel>"
    )