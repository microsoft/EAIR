"""Run any confirmed risk environment through one stable CLI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from enterprise_toolkit.resources import resource_path
from risk_environments import CONFIRMED_RISKS, get_risk_environment


def run_environment(
    risk_id: str,
    config: Path | None = None,
    runs_dir: Path = Path("runs"),
    extra_args: Sequence[str] = (),
) -> int:
    """Run a confirmed environment with its existing implementation."""
    environment = get_risk_environment(risk_id)
    if config is not None:
        config_path = config
    else:
        config_path = Path(environment.smoke_config)
        if not config_path.is_file():
            config_path = resource_path(environment.smoke_config)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config does not exist: {config_path}")

    command = [
        sys.executable,
        "-m",
        environment.run_module,
        "--config",
        str(config_path),
        "--runs-dir",
        str(runs_dir),
        *extra_args,
    ]
    return subprocess.run(command, check=False).returncode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a confirmed enterprise risk environment."
    )
    parser.add_argument("risk_id", nargs="?", choices=CONFIRMED_RISKS)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument(
        "--list",
        action="store_true",
        help="list confirmed environments and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args, extra_args = parser.parse_known_args(argv)

    if args.list:
        for environment in CONFIRMED_RISKS.values():
            print(f"{environment.risk_id:16} {environment.display_name}")
        return 0
    if args.risk_id is None:
        parser.error("risk_id is required unless --list is used")

    return run_environment(
        args.risk_id,
        config=args.config,
        runs_dir=args.runs_dir,
        extra_args=extra_args,
    )


if __name__ == "__main__":
    raise SystemExit(main())