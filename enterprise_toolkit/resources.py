"""Resolve the release's selected configurations in a checkout or installation."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path, PurePosixPath


_PACKAGE_ROOT = Path(__file__).resolve().parent
_PAPER_IDS = frozenset({"A1", "B1", "C1", "D1", "F1"})


def load_catalog() -> dict:
    """Read fresh catalog metadata without sharing mutable state between callers."""
    return json.loads((_PACKAGE_ROOT / "catalog.json").read_text(encoding="utf-8"))


def _relative_path(relative_path: str) -> str:
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or any(character in relative_path for character in ("\\", ":", "\x00"))
        or PurePosixPath(relative_path).is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.split("/"))
    ):
        raise ValueError(f"Expected a safe, relative POSIX resource path: {relative_path!r}")
    return relative_path


def selected_config_paths(catalog: dict | None = None) -> tuple[str, ...]:
    """Return the sorted smoke, recommended, and supplemental config union."""
    metadata = load_catalog() if catalog is None else catalog
    selected = set()
    for world in metadata["worlds"]:
        if world["paper_id"] not in _PAPER_IDS:
            raise ValueError(f"Risk is outside this release: {world['paper_id']}")
        selected.update(
            _relative_path(path)
            for path in (
                world["smoke_config"],
                *world.get("recommended_configs", []),
                *world.get("supplemental_configs", []),
            )
        )
    return tuple(sorted(selected))


def _contained_file(root: Path, relative_path: str) -> Path | None:
    candidate = root / relative_path
    for ancestor in (candidate, *candidate.parents):
        if ancestor.is_symlink():
            raise ValueError(f"Resource must not traverse a symlink: {relative_path!r}")
        if ancestor == root:
            break
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"Resource escapes its root: {relative_path!r}")
    return candidate if candidate.is_file() else None


def resource_path(relative_path: str) -> Path:
    """Return an existing selected config; reject traversal and unselected files."""
    relative_path = _relative_path(relative_path)
    if relative_path not in selected_config_paths():
        raise ValueError(f"Resource is not selected by the release catalog: {relative_path!r}")

    assets_root = _PACKAGE_ROOT / "assets"
    if assets_root.exists():
        asset = _contained_file(assets_root, relative_path)
        if asset is not None:
            return asset
    else:
        source_root = _PACKAGE_ROOT.parent
        project_file = source_root / "pyproject.toml"
        if (
            project_file.is_file()
            and (source_root / "_toolkit_build.py").is_file()
            and (source_root / "setup.py").is_file()
        ):
            metadata = tomllib.loads(project_file.read_text(encoding="utf-8"))
            if metadata.get("project", {}).get("name") == "enterprise-microworld":
                source = _contained_file(source_root, relative_path)
                if source is not None:
                    return source

    raise FileNotFoundError(f"Packaged configuration is missing: {relative_path}")