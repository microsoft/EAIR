"""Deterministic semantic-pseudonym manifest generation."""

from __future__ import annotations

import hashlib
import re

from verifier.schemas.env_metadata import EnvMetadata
from verifier.schemas.sanitize_manifest import SanitizeManifest
from verifier.schemas.trajectory import Trajectory


SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    slug = SLUG_RE.sub("_", value.casefold()).strip("_")
    return slug or "item"


def _semantic_slug(value: str, limit: int = 4) -> str:
    words = _slug(value).split("_")
    return "_".join(words[:limit])


def _stable_ref(prefix: str, value: str, version: str) -> str:
    digest = hashlib.sha256(f"{version}\0{value}".encode()).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _semantic_ref(
    prefix: str, semantic_value: str, source_id: str, index: int, version: str
) -> str:
    digest = hashlib.sha256(f"{version}\0{source_id}".encode()).hexdigest()[:6]
    return f"{prefix}_{_semantic_slug(semantic_value)}_{index}_{digest}"


def build_manifest(
    metadata: EnvMetadata,
    trajectory: Trajectory,
    sanitizer_version: str = "1",
) -> SanitizeManifest:
    agent_ids = {
        role.agent_id: _semantic_ref(
            "agent", role.title, role.agent_id, index, sanitizer_version
        )
        for index, role in enumerate(metadata.roles, start=1)
    }
    tool_ids = {
        tool.tool_id: _semantic_ref(
            "tool", tool.description, tool.tool_id, index, sanitizer_version
        )
        for index, tool in enumerate(metadata.tools, start=1)
    }
    document_ids = {
        document.doc_id: _semantic_ref(
            "doc", document.title, document.doc_id, index, sanitizer_version
        )
        for index, document in enumerate(metadata.documents, start=1)
    }
    policy_ids = {
        policy.policy_id: _semantic_ref(
            "policy", "rule", policy.policy_id, index, sanitizer_version
        )
        for index, policy in enumerate(metadata.policies, start=1)
    }
    return SanitizeManifest(
        sanitizer_version=sanitizer_version,
        env_ids={metadata.env_ref: _stable_ref("env", metadata.env_ref, sanitizer_version)},
        agent_ids=agent_ids,
        tool_ids=tool_ids,
        document_ids=document_ids,
        policy_ids=policy_ids,
        episode_ids={
            trajectory.episode_id: _stable_ref(
                "episode", trajectory.episode_id, sanitizer_version
            )
        },
    )
