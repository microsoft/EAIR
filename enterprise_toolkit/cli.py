"""Command-line workflows for Enterprise Agent Risk (EAIR)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from enterprise_toolkit.resources import load_catalog, resource_path


def _world(identifier: str) -> dict:
    for world in load_catalog()["worlds"]:
        if identifier.casefold() in {
            world["paper_id"].casefold(), world["risk_id"].casefold()
        }:
            return world
    raise ValueError(f"Unknown world {identifier!r}; choose A1, B1, C1, D1, or F1")


def _list_worlds(args: argparse.Namespace) -> None:
    catalog = load_catalog()
    if args.json:
        print(json.dumps(catalog, indent=2))
        return
    print("ID\tRisk\tStudy configurations")
    for world in catalog["worlds"]:
        print(
            f"{world['paper_id']}\t{world['display_name']}\t"
            f"{len(world['recommended_configs'])}"
        )
    print(f"Verifier: {catalog['verifier']['profile']}")


def _show_world(args: argparse.Namespace) -> None:
    print(json.dumps(_world(args.world), indent=2))


def _run_builtin(args: argparse.Namespace) -> int:
    from run_risk import run_environment

    world = _world(args.world)
    config = args.config if args.config is not None else resource_path(world["smoke_config"])
    return run_environment(world["risk_id"], config=config, runs_dir=args.out)


def _study(args: argparse.Namespace) -> int:
    from enterprise_toolkit.commands import run_study

    return run_study(args, _world(args.world))


def _config(args: argparse.Namespace) -> None:
    world = _world(args.world)
    selected = (
        [world["smoke_config"]] if args.kind == "smoke"
        else world.get(f"{args.kind}_configs", [])
    )
    if not 1 <= args.index <= len(selected):
        raise ValueError(f"{args.kind} index must be between 1 and {len(selected)}")
    source = resource_path(selected[args.index - 1])
    if args.out is None:
        print(source)
        return
    content = source.read_bytes()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("xb") as destination:
        destination.write(content)
    print(args.out)


def _init_world(args: argparse.Namespace) -> None:
    from enterprise_toolkit.scaffold import create_world

    print(create_world(args.destination, args.world_id))


def _run_world(args: argparse.Namespace) -> None:
    from enterprise_toolkit.custom import WorldSpec, run_conversation

    spec = WorldSpec.load(args.spec)
    if args.out.exists():
        raise FileExistsError(f"episode destination already exists: {args.out}")
    backend = None
    if not args.mock:
        if not args.model:
            raise ValueError("--model is required with --provider")
        from llm.client import AnthropicBackend, OpenAIBackend, OpenRouterBackend, TRAPIBackend

        backend_type = {
            "openai": OpenAIBackend, "anthropic": AnthropicBackend,
            "openrouter": OpenRouterBackend, "trapi": TRAPIBackend,
        }[args.provider]
        backend = backend_type(args.model)
    elif args.model:
        raise ValueError("--model cannot be combined with --mock")
    episode = run_conversation(
        spec, args.episode_id, backend, mock=args.mock, temperature=args.temperature
    )
    print(episode.write(args.out))


def _export_world(args: argparse.Namespace) -> None:
    from enterprise_toolkit.custom import WorldEpisode, export_custom_episode

    bundle, manifest = export_custom_episode(
        WorldEpisode.load(args.episode), args.out / "bundles", args.out / "private-manifests"
    )
    print(json.dumps({"bundle": str(bundle), "manifest": str(manifest)}, indent=2))


def _prepare_audit(episode, output: Path, scope: str, profile: str, allowed_hosts, truth=None) -> dict:
    from enterprise_toolkit.custom import export_custom_episode
    from verifier.orchestrator.materialize import materialize_auditor_task
    from verifier.schemas.sanitize_manifest import SanitizeManifest

    bundle, manifest_path = export_custom_episode(
        episode, output / "bundles", output / "private-manifests"
    )
    manifest = SanitizeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    task = materialize_auditor_task(
        bundle, output / "auditor-task", truth, manifest, allowed_hosts,
        profile=profile, scope_text=scope,
    )
    return {
        "bundle": str(bundle), "manifest": str(manifest_path), "auditor_task": str(task),
        "profile": profile, "discovery_only": truth is None,
        "semantic_audit_executed": False, "mitigation_executed": False,
    }


def _audit_world(args: argparse.Namespace) -> None:
    from enterprise_toolkit.custom import WorldEpisode
    from enterprise_toolkit.scaffold import template_text

    episode = WorldEpisode.load(args.episode)
    scope = args.scope.read_text(encoding="utf-8") if args.scope else template_text("scope.md")
    if not scope.strip():
        raise ValueError("audit scope must not be empty")
    truth = None
    if args.ground_truth is not None:
        truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
        if not isinstance(truth, dict):
            raise ValueError("ground truth must be a JSON object")
    if args.out.exists():
        raise FileExistsError(f"audit destination already exists: {args.out}")
    result = _prepare_audit(episode, args.out, scope, args.profile, args.allowed_hosts, truth)
    print(json.dumps(result, indent=2))


def _demo(args: argparse.Namespace) -> None:
    from enterprise_toolkit.custom import WorldSpec, run_conversation
    from enterprise_toolkit.scaffold import create_world, template_text

    if args.out.exists():
        raise FileExistsError(f"demo destination already exists: {args.out}")
    world = create_world(args.out / "world")
    episode = run_conversation(WorldSpec.load(world / "world.yaml"), "demo-001", mock=True)
    episode_path = episode.write(args.out / "episode")
    result = _prepare_audit(
        episode, args.out, template_text("scope.md"), "v3-topology", ["api.openai.com"]
    )
    result.update(execution_mode="mock", world=str(world), episode=str(episode_path))
    (args.out / "demo.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


def create_parser() -> argparse.ArgumentParser:
    from enterprise_toolkit.commands import build_graph, check_report, open_docs

    parser = argparse.ArgumentParser(
        prog="eair",
        description="Enterprise Agent Risk (EAIR): enterprise interaction-risk research toolkit",
    )
    parser.add_argument("--version", action="version", version=load_catalog()["release_version"])
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="List the five released worlds and verifier profile")
    listing.add_argument("--json", action="store_true", help="Print the complete release catalog")
    listing.set_defaults(handler=_list_worlds)

    info = commands.add_parser("info", help="Show a world's selected studies and report provenance")
    info.add_argument("world", help="Paper ID or risk ID, for example A1 or authority_bias")
    info.set_defaults(handler=_show_world)

    builtin = commands.add_parser("run", help="Run a paper world; defaults to its packaged offline smoke config")
    builtin.add_argument("world", help="A1, B1, C1, D1, F1, or a runtime risk ID")
    builtin.add_argument("--config", type=Path, help="Explicit runtime config; may enable paid model execution")
    builtin.add_argument("--out", type=Path, required=True, help="Directory containing the generated run")
    builtin.set_defaults(handler=_run_builtin)

    study = commands.add_parser("study", help="Preview a report-selected study; execution requires --execute")
    study.add_argument("world")
    study.add_argument("--index", type=int, default=1, help="One-based recommended configuration index")
    study.add_argument("--config", type=Path)
    study.add_argument("--out", type=Path, required=True)
    study.add_argument("--execute", action="store_true", help="Run the displayed command; may incur model charges")
    study.add_argument("--mock", action="store_true", help="Run the A1 title-effect study with offline fixtures")
    study.add_argument("--calibration-config", type=Path, help="F1 matched solo calibration configuration")
    study.add_argument("--max-workers", type=int, default=1, help="F1 study concurrency (default: 1)")
    study.set_defaults(handler=_study)

    config = commands.add_parser("config", help="Locate or copy an exact selected configuration")
    config.add_argument("world")
    config.add_argument("--kind", choices=("smoke", "recommended", "supplemental"), default="recommended")
    config.add_argument("--index", type=int, default=1, help="One-based index within the selected kind")
    config.add_argument("--out", type=Path, help="Copy without overwriting an existing file")
    config.set_defaults(handler=_config)

    init = commands.add_parser("init", help="Generate an editable custom world and audit scope")
    init.add_argument("destination", type=Path)
    init.add_argument("--world-id", default="purchase_review")
    init.set_defaults(handler=_init_world)

    run = commands.add_parser("run-world", help="Run a conversation world with an explicit execution mode")
    run.add_argument("spec", type=Path)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--episode-id", default="episode-001")
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true")
    mode.add_argument("--provider", choices=("openai", "anthropic", "openrouter", "trapi"))
    run.add_argument("--model")
    run.add_argument("--temperature", type=float, default=0.0)
    run.set_defaults(handler=_run_world)

    export = commands.add_parser("export-world", help="Export a custom WorldEpisode with private identity mapping")
    export.add_argument("episode", type=Path)
    export.add_argument("--out", type=Path, required=True)
    export.set_defaults(handler=_export_world)

    audit = commands.add_parser("audit-world", help="Prepare a sanitized custom-world Harbor audit task")
    audit.add_argument("episode", type=Path)
    audit.add_argument("--out", type=Path, required=True)
    audit.add_argument("--scope", type=Path)
    audit.add_argument("--ground-truth", type=Path, help="Optional private reference labels; default is discovery-only")
    audit.add_argument("--profile", choices=("v3-topology", "v3-annotated"), default="v3-topology")
    audit.add_argument("--allowed-host", action="append", dest="allowed_hosts")
    audit.set_defaults(handler=_audit_world)

    demo = commands.add_parser("demo", help="Offline mock trajectory, export, and audit-task preparation")
    demo.add_argument("--out", type=Path, required=True)
    demo.set_defaults(handler=_demo)

    commands.add_parser("verify", help="Export, prepare, execute, and review isolated V3 tasks (verify --help)")

    graph = commands.add_parser("graph", help="Build a navigation graph from a sanitized bundle")
    graph.add_argument("bundle", type=Path)
    graph.add_argument("--out", type=Path, required=True)
    graph.add_argument("--profile", choices=("v3-topology", "v3-annotated"), default="v3-topology")
    graph.set_defaults(handler=build_graph)

    validate = commands.add_parser("validate", help="Check a report's schema and cited evidence, not semantic correctness")
    validate.add_argument("report", type=Path)
    validate.add_argument("--bundle", type=Path, required=True)
    validate.set_defaults(handler=check_report)

    docs = commands.add_parser("docs", help="Open the bundled offline documentation website")
    docs.add_argument("--no-open", action="store_true", help="Print the HTML path without opening a browser")
    docs.add_argument("--export", type=Path, help="Copy the complete website into a new directory")
    docs.set_defaults(handler=open_docs)

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "verify":
        from verifier.cli import main as verifier_main

        try:
            return verifier_main(arguments[1:], prog="eair verify")
        except ModuleNotFoundError as error:
            argparse.ArgumentParser(prog="eair verify").error(
                f"Missing dependency {error.name!r}; install the required model or Harbor environment"
            )
        except (ValueError, OSError, RuntimeError) as error:
            argparse.ArgumentParser(prog="eair verify").error(str(error))
    parser = create_parser()
    args = parser.parse_args(arguments)
    try:
        result = args.handler(args)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    except ModuleNotFoundError as error:
        parser.error(f"Missing dependency {error.name!r}; install the toolkit's 'live' extra for model execution")
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())