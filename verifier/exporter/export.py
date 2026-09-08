"""Atomic deterministic writer for sanitized verifier bundles."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import hashlib
from pathlib import Path
from typing import Iterable, Mapping

from verifier.exporter.sanitizer import (
    DEFAULT_DENYLIST,
    SourceInventory,
    _canonical_json,
    sanitize_bundle,
)
from verifier.exporter.adapters import build_source_snapshot
from verifier.exporter.episode_reader import read_episode_trajectory
from verifier.exporter.manifest import build_manifest
from verifier.schemas.env_metadata import EnvMetadata
from verifier.schemas.sanitize_manifest import SanitizeManifest
from verifier.schemas.trajectory import Trajectory


def export_bundle(
    output_dir: Path,
    metadata: EnvMetadata,
    trajectory: Trajectory,
    documents: Mapping[str, bytes | str],
    manifest: SanitizeManifest,
    source_inventory: SourceInventory,
    denylist: Iterable[str] = DEFAULT_DENYLIST,
) -> Path:
    """Sanitize, validate, and atomically write one complete bundle."""
    bundle = sanitize_bundle(
        metadata,
        trajectory,
        documents,
        manifest,
        source_inventory,
        denylist,
    )
    output_dir = output_dir.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        (temporary / "documents").mkdir()
        (temporary / "env_metadata.json").write_bytes(
            _canonical_json(bundle.metadata.model_dump(mode="json"))
        )
        (temporary / "trajectory.json").write_bytes(
            _canonical_json(bundle.trajectory.model_dump(mode="json"))
        )
        for relative_path, content in bundle.documents.items():
            destination = temporary / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        os.replace(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output_dir


def export_episode_bundle(
    risk_id: str,
    episode_dir: Path,
    bundles_root: Path,
    manifests_root: Path,
    sanitizer_version: str = "1",
    denylist: Iterable[str] = DEFAULT_DENYLIST,
) -> tuple[Path, Path]:
    """Export one confirmed-risk episode and keep identity mapping host-only."""
    snapshot = build_source_snapshot(risk_id, episode_dir)
    source_episode_id = str(
        json.loads((episode_dir / "meta.json").read_text(encoding="utf-8"))["episode_id"]
    )
    trajectory = read_episode_trajectory(
        episode_dir,
        source_episode_id,
        snapshot.agents,
        snapshot.task_spec,
        snapshot.outcome,
    )
    manifest = build_manifest(snapshot.metadata, trajectory, sanitizer_version)
    bundle_id = hashlib.sha256(
        f"{risk_id}\0{source_episode_id}\0{sanitizer_version}".encode("utf-8")
    ).hexdigest()[:20]
    bundle_dir = bundles_root / f"bundle_{bundle_id}"
    manifest_path = manifests_root / f"bundle_{bundle_id}.manifest.json"
    if manifest_path.resolve().is_relative_to(bundle_dir.resolve()):
        raise ValueError("manifest store must be outside the shipped bundle")
    export_bundle(
        bundle_dir,
        snapshot.metadata,
        trajectory,
        snapshot.documents,
        manifest,
        snapshot.inventory,
        denylist,
    )
    manifests_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return bundle_dir, manifest_path
