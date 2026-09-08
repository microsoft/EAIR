"""Leakage audit for auditor outputs and shipped bundles."""

from pathlib import Path
from typing import Iterable

from verifier.exporter.sanitizer import DEFAULT_DENYLIST, lint_leakage


def audit_paths(
    paths: Iterable[Path],
    denylist: Iterable[str] = DEFAULT_DENYLIST,
) -> None:
    payloads = []
    for path in paths:
        if path.is_dir():
            payloads.extend(
                (child.as_posix(), child.read_bytes())
                for child in path.rglob("*")
                if child.is_file()
            )
        elif path.is_file():
            payloads.append((path.as_posix(), path.read_bytes()))
    lint_leakage(payloads, denylist)
