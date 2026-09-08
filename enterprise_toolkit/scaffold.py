"""Generate an editable world from packaged, validated starter resources."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import yaml

from enterprise_toolkit.custom import WorldSpec


def template_text(name: str) -> str:
    if name not in {"world.yaml", "scope.md", "README.md"}:
        raise ValueError(f"Unknown starter resource: {name}")
    return files("enterprise_toolkit").joinpath("templates", name).read_text(encoding="utf-8")


def create_world(destination: Path, world_id: str = "purchase_review") -> Path:
    data = yaml.safe_load(template_text("world.yaml"))
    data["world_id"] = world_id
    data["metadata"]["env_ref"] = world_id
    spec = WorldSpec.model_validate(data)
    texts = {
        "world.yaml": yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False),
        "scope.md": template_text("scope.md"),
        "README.md": template_text("README.md"),
    }
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in texts.items():
        (destination / name).write_text(content, encoding="utf-8")
    return destination