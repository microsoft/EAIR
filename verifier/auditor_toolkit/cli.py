"""Console entry points installed in the auditor Harbor image."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import ModuleType
from typing import Sequence

from verifier.auditor_toolkit import graph, topology
from verifier.auditor_toolkit.bundle import Bundle, write_json
from verifier.auditor_toolkit.graph import (
    check_permission,
    diff_summary,
)
from verifier.auditor_toolkit.validation import validate_report
from verifier.orchestrator.profiles import GRAPH_PROFILES, resolve_graph_profile


def _add_graph_profile(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        choices=GRAPH_PROFILES,
        help="graph profile (default: VERIFIER_GRAPH_PROFILE or v3-annotated)",
    )


def _graph_tools(parser: argparse.ArgumentParser, profile: str | None) -> ModuleType:
    try:
        selected = resolve_graph_profile(profile)
    except ValueError as exc:
        parser.error(str(exc))
    return topology if selected == "v3-topology" else graph


def build_graph_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    _add_graph_profile(parser)
    args = parser.parse_args(argv)
    tools = _graph_tools(parser, args.profile)
    write_json(args.output, tools.build_interaction_graph(Bundle.load(args.bundle)))
    return 0


def validate_report_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    args = parser.parse_args(argv)
    result = validate_report(args.report, Bundle.load(args.bundle))
    for error in result.errors:
        print(error)
    print("valid" if result.valid else f"invalid: {len(result.errors)} violation(s)")
    return 0 if result.valid else 1


def get_steps_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    parser.add_argument("--step-id", action="append", default=[])
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    parser.add_argument("--sender")
    parser.add_argument("--receiver")
    args = parser.parse_args(argv)
    steps = Bundle.load(args.bundle).trajectory.steps
    selected = [
        step for step in steps
        if (not args.step_id or step.step_id in args.step_id)
        and (args.start is None or step.t >= args.start)
        and (args.end is None or step.t <= args.end)
        and (args.sender is None or step.sender == args.sender)
        and (args.receiver is None or step.receiver == args.receiver)
    ]
    print(json.dumps([step.model_dump(mode="json") for step in selected], indent=2))
    return 0


def get_policy_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy_id")
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    args = parser.parse_args(argv)
    policies = {item.policy_id: item for item in Bundle.load(args.bundle).metadata.policies}
    if args.policy_id not in policies:
        print(f"unknown policy: {args.policy_id}")
        return 1
    print(policies[args.policy_id].model_dump_json(indent=2))
    return 0


def search_policies_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    args = parser.parse_args(argv)
    query = args.query.casefold()
    matches = [
        item.model_dump(mode="json")
        for item in Bundle.load(args.bundle).metadata.policies
        if query in item.text.casefold() or query in item.policy_id.casefold()
    ]
    print(json.dumps(matches, indent=2))
    return 0


def read_doc_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("doc_id")
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    args = parser.parse_args(argv)
    try:
        print(Bundle.load(args.bundle).read_document(args.doc_id))
    except KeyError as exc:
        print(exc.args[0])
        return 1
    return 0


def trace_provenance_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("step_id")
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    _add_graph_profile(parser)
    args = parser.parse_args(argv)
    tools = _graph_tools(parser, args.profile)
    if tools is topology:
        parser.error(
            "provenance annotations are unavailable in topology-only mode; "
            "use get-steps for raw evidence"
        )
    graph_data = tools.build_interaction_graph(Bundle.load(args.bundle))
    print(json.dumps(tools.trace_provenance(graph_data, args.step_id), indent=2))
    return 0


def diff_summary_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_step")
    parser.add_argument("summary_step")
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    args = parser.parse_args(argv)
    try:
        result = diff_summary(Bundle.load(args.bundle), args.source_step, args.summary_step)
    except KeyError as exc:
        print(exc.args[0])
        return 1
    print(json.dumps(result, indent=2))
    return 0


def check_permission_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("agent")
    parser.add_argument("action")
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    args = parser.parse_args(argv)
    try:
        result = check_permission(Bundle.load(args.bundle), args.agent, args.action)
    except KeyError as exc:
        print(exc.args[0])
        return 1
    print(json.dumps(result, indent=2))
    return 0


def graph_query_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pattern")
    parser.add_argument("--bundle", type=Path, default=Path("/app/bundle"))
    _add_graph_profile(parser)
    args = parser.parse_args(argv)
    tools = _graph_tools(parser, args.profile)
    try:
        result = tools.graph_query(
            tools.build_interaction_graph(Bundle.load(args.bundle)), args.pattern
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, indent=2))
    return 0
