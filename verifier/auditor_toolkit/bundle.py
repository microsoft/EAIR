"""Validated read-only access to a shipped auditor bundle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from verifier.schemas.env_metadata import EnvMetadata
from verifier.schemas.trajectory import Trajectory


@dataclass(frozen=True)
class Bundle:
    root: Path
    metadata: EnvMetadata
    trajectory: Trajectory

    @classmethod
    def load(cls, root: Path) -> "Bundle":
        root = root.resolve()
        metadata = EnvMetadata.model_validate_json(
            (root / "env_metadata.json").read_text(encoding="utf-8")
        )
        trajectory = Trajectory.model_validate_json(
            (root / "trajectory.json").read_text(encoding="utf-8")
        )
        return cls(root=root, metadata=metadata, trajectory=trajectory)

    def read_document(self, doc_id: str) -> str:
        try:
            document = next(
                item for item in self.metadata.documents if item.doc_id == doc_id
            )
        except StopIteration as exc:
            raise KeyError(f"unknown document: {doc_id}") from exc
        path = (self.root / document.path).resolve()
        if self.root not in path.parents:
            raise ValueError(f"document path escapes bundle: {document.path}")
        return path.read_text(encoding="utf-8")

    def as_summary(self) -> dict:
        return {
            "env_ref": self.metadata.env_ref,
            "episode_id": self.trajectory.episode_id,
            "roles": len(self.metadata.roles),
            "steps": len(self.trajectory.steps),
            "policies": len(self.metadata.policies),
            "documents": len(self.metadata.documents),
        }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
