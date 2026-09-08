"""Environment-level development and held-out split enforcement."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal


@dataclass(frozen=True)
class EnvironmentSplit:
    environment_id: str
    split: Literal["dev", "held_out"]


def assign_environment_splits(
    environment_ids: Iterable[str],
    held_out_fraction: float = 0.2,
    salt: str = "verifier-split-v1",
) -> list[EnvironmentSplit]:
    if not 0 < held_out_fraction < 1:
        raise ValueError("held_out_fraction must be between 0 and 1")
    unique_ids = sorted(set(environment_ids))
    if len(unique_ids) < 2:
        raise ValueError("at least two environments are required for a held-out split")
    ranked = sorted(
        unique_ids,
        key=lambda identifier: hashlib.sha256(
            f"{salt}\0{identifier}".encode("utf-8")
        ).digest(),
    )
    held_out_count = max(1, round(len(ranked) * held_out_fraction))
    held_out = set(ranked[:held_out_count])
    return [
        EnvironmentSplit(identifier, "held_out" if identifier in held_out else "dev")
        for identifier in unique_ids
    ]


def assert_template_frozen(
    current_digest: str,
    frozen_digest: str,
    split: Literal["dev", "held_out"],
) -> None:
    if split == "held_out" and current_digest != frozen_digest:
        raise ValueError("instruction/toolkit changed after the held-out freeze")


def content_digest(root: Path, paths: Iterable[Path]) -> str:
    """Hash file identities and bytes so a frozen evaluation surface is portable."""
    digest = hashlib.sha256()
    root = root.resolve()
    for path in sorted((item.resolve() for item in paths), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
