"""Command-line interface for the Harbor verifier pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from risk_environments import CONFIRMED_RISKS
from verifier.exporter import export_episode_bundle
from verifier.orchestrator.materialize import (
    materialize_auditor_task,
    materialize_coder_task,
    materialize_repair_auditor_task,
)
from verifier.orchestrator.pipeline import (
    TRAPI_AGENT,
    TRAPI_AGENT_KWARGS,
    TRAPI_MODEL,
    parse_agent_kwargs,
    run_harbor,
)
from verifier.orchestrator.profiles import GRAPH_PROFILES
from verifier.schemas.sanitize_manifest import SanitizeManifest


def _json_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Build and run Harbor-isolated interaction-risk verification tasks."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export", help="export one sanitized episode bundle")
    export.add_argument("risk_id", choices=CONFIRMED_RISKS)
    export.add_argument("episode_dir", type=Path)
    export.add_argument("--bundles-root", type=Path, default=Path("verifier/bundles"))
    export.add_argument("--manifests-root", type=Path, default=Path("verifier/manifests"))
    export.add_argument("--sanitizer-version", default="1")

    auditor = subparsers.add_parser("auditor-task", help="materialize an auditor Harbor task")
    auditor.add_argument("bundle_dir", type=Path)
    auditor.add_argument("ground_truth", type=Path, help="JSON object, or '-' with --discovery-only")
    auditor.add_argument("manifest", type=Path)
    auditor.add_argument("output_dir", type=Path)
    auditor.add_argument("--allowed-host", action="append", dest="allowed_hosts")
    auditor.add_argument("--profile", choices=GRAPH_PROFILES, default="v3-topology")
    auditor.add_argument("--scope", type=Path, help="UTF-8 audit-scope text file")
    auditor.add_argument(
        "--discovery-only", action="store_true",
        help="validate the report without reference scoring; use '-' for ground_truth",
    )

    coder = subparsers.add_parser("coder-task", help="materialize a coder Harbor task")
    coder.add_argument("risk_id", help="confirmed risk ID, or custom world ID with --custom-environment")
    coder.add_argument("environment_source", type=Path)
    coder.add_argument("report", type=Path)
    coder.add_argument("manifest", type=Path)
    coder.add_argument("output_dir", type=Path)
    coder.add_argument("--allowed-host", action="append", dest="allowed_hosts")
    coder.add_argument("--smoke-command", help="JSON string array")
    coder.add_argument("--utility-command", help="JSON string array")
    coder.add_argument("--checks", type=Path, help="JSON file with smoke_command and utility_command string arrays")
    coder.add_argument(
        "--custom-environment", action="store_true",
        help="opt in to a custom world whose ID matches a manifest.env_ids key",
    )

    repair_auditor = subparsers.add_parser(
        "repair-auditor-task",
        help="materialize an independent Repair Auditor Harbor task",
    )
    repair_auditor.add_argument("pristine_environment", type=Path)
    repair_auditor.add_argument("modified_environment", type=Path)
    repair_auditor.add_argument("report", type=Path)
    repair_auditor.add_argument("repair_report", type=Path)
    repair_auditor.add_argument("output_dir", type=Path)
    repair_auditor.add_argument(
        "--allowed-host", action="append", dest="allowed_hosts"
    )

    run = subparsers.add_parser("run", help="run a materialized task with Harbor")
    run.add_argument("task", type=Path)
    run.add_argument(
        "--profile",
        choices=("trapi-gpt56-sol-high", "custom"),
        default="trapi-gpt56-sol-high",
    )
    run.add_argument("--agent")
    run.add_argument("--model")
    run.add_argument("--agent-kwarg", action="append", default=[])
    run.add_argument("--runs-dir", type=Path, default=Path("verifier/runs"))
    run.add_argument("--n-concurrent", type=int, default=1)
    return parser


def _command_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed or not all(
        isinstance(item, str) and item.strip() for item in parsed
    ):
        raise ValueError("command must be a nonempty JSON string array with nonempty arguments")
    return parsed


def main(argv: Sequence[str] | None = None, *, prog: str | None = None) -> int:
    parser = _parser(prog)
    args = parser.parse_args(argv)
    if args.command == "export":
        bundle, manifest = export_episode_bundle(
            args.risk_id,
            args.episode_dir,
            args.bundles_root,
            args.manifests_root,
            args.sanitizer_version,
        )
        print(json.dumps({"bundle": str(bundle), "manifest": str(manifest)}))
        return 0
    if args.command == "auditor-task":
        if args.discovery_only != (args.ground_truth == Path("-")):
            parser.error("use --discovery-only together with '-' as ground_truth")
        task = materialize_auditor_task(
            args.bundle_dir,
            args.output_dir,
            None if args.discovery_only else _json_object(args.ground_truth),
            SanitizeManifest.model_validate_json(args.manifest.read_text(encoding="utf-8")),
            args.allowed_hosts,
            profile=args.profile,
            scope_text=args.scope.read_text(encoding="utf-8") if args.scope is not None else None,
        )
        print(task)
        return 0
    if args.command == "coder-task":
        if not args.custom_environment and args.risk_id not in CONFIRMED_RISKS:
            parser.error(
                f"unknown or unconfirmed risk {args.risk_id!r}; choose "
                f"{', '.join(CONFIRMED_RISKS)} or explicitly use --custom-environment"
            )
        smoke_command = _command_list(args.smoke_command)
        utility_command = _command_list(args.utility_command)
        if args.checks is not None:
            if args.smoke_command is not None or args.utility_command is not None:
                parser.error("--checks cannot be combined with --smoke-command or --utility-command")
            checks = _json_object(args.checks)
            if set(checks) != {"smoke_command", "utility_command"}:
                parser.error("--checks requires exactly smoke_command and utility_command")
            smoke_command = _command_list(json.dumps(checks["smoke_command"]))
            utility_command = _command_list(json.dumps(checks["utility_command"]))
        task = materialize_coder_task(
            args.risk_id,
            args.environment_source,
            args.report,
            SanitizeManifest.model_validate_json(
                args.manifest.read_text(encoding="utf-8")
            ),
            args.output_dir,
            smoke_command,
            utility_command,
            args.allowed_hosts,
            custom_environment=args.custom_environment,
        )
        print(task)
        return 0
    if args.command == "repair-auditor-task":
        task = materialize_repair_auditor_task(
            args.pristine_environment,
            args.modified_environment,
            args.report,
            args.repair_report,
            args.output_dir,
            args.allowed_hosts,
        )
        print(task)
        return 0
    explicit_kwargs = parse_agent_kwargs(args.agent_kwarg)
    if args.profile == "trapi-gpt56-sol-high":
        agent = args.agent or TRAPI_AGENT
        model = args.model or TRAPI_MODEL
        agent_kwargs = {**TRAPI_AGENT_KWARGS, **explicit_kwargs}
        trapi_auth = True
    else:
        if not args.agent or not args.model:
            raise ValueError("custom profile requires --agent and --model")
        agent = args.agent
        model = args.model
        agent_kwargs = explicit_kwargs
        trapi_auth = False
    records = run_harbor(
        args.task,
        agent,
        model,
        args.runs_dir,
        args.n_concurrent,
        agent_kwargs=agent_kwargs,
        trapi_auth=trapi_auth,
    )
    print(json.dumps([
        {
            "job_id": record.job_id,
            "trial_id": record.trial_id,
            "artifacts": {key: str(path) for key, path in record.artifacts.items()},
            "rewards": record.rewards,
        }
        for record in records
    ], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
