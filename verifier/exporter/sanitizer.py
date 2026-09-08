"""Deterministic identity sanitization and bundle isolation gates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from verifier.schemas.env_metadata import EnvMetadata
from verifier.schemas.sanitize_manifest import SanitizeManifest
from verifier.schemas.trajectory import Trajectory


RISK_OUTCOME_KEY = re.compile(
    r"(?:risk|violation|leak|drift|bias|gaming|collusion|confused_deputy)",
    re.IGNORECASE,
)
FORBIDDEN_METADATA_KEY = re.compile(
    r"(?:path|repo|class|source_code|scenario_tag|ground_truth|risk)",
    re.IGNORECASE,
)
DEFAULT_DENYLIST = (
    "enterprise-microworld",
    "AgentRisk",
    "authority_bias_env",
    "authority_deference",
    "kpi_gaming",
    "semantic_drift",
    "confused_deputy",
    "provenance_paradox",
    "tacit_collusion",
    "aggregator_sway",
)


class CompletenessError(ValueError):
    """The sanitized bundle omits or dangles substantive source data."""


class LeakageError(ValueError):
    """Internal experiment identity leaked into a shipped bundle."""


class SourceInventory(BaseModel):
    """Trusted source-side full inventory used for two-sided parity checks."""

    model_config = ConfigDict(extra="forbid")

    role_ids: set[str] = Field(default_factory=set)
    policy_ids: set[str] = Field(default_factory=set)
    tool_ids: set[str] = Field(default_factory=set)
    document_ids: set[str] = Field(default_factory=set)


@dataclass(frozen=True)
class SanitizedBundle:
    metadata: EnvMetadata
    trajectory: Trajectory
    documents: dict[str, bytes]


def _replace_text(value: str, substitutions: Mapping[str, str]) -> str:
    result = value
    for source in sorted(substitutions, key=lambda item: (-len(item), item)):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])"
        result = re.sub(pattern, substitutions[source], result, flags=re.IGNORECASE)
    return result


def _replace_value(value: Any, substitutions: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _replace_text(value, substitutions)
    if isinstance(value, list):
        return [_replace_value(item, substitutions) for item in value]
    if isinstance(value, dict):
        return {
            _replace_text(str(key), substitutions): _replace_value(item, substitutions)
            for key, item in value.items()
        }
    return value


def _clean_metadata(value: Any, substitutions: Mapping[str, str]) -> Any:
    if isinstance(value, list):
        return [_clean_metadata(item, substitutions) for item in value]
    if isinstance(value, dict):
        return {
            _replace_text(str(key), substitutions): _clean_metadata(item, substitutions)
            for key, item in value.items()
            if not FORBIDDEN_METADATA_KEY.search(str(key))
        }
    return _replace_value(value, substitutions)


def _all_substitutions(manifest: SanitizeManifest) -> dict[str, str]:
    result: dict[str, str] = {}
    for mapping in (
        manifest.env_ids,
        manifest.agent_ids,
        manifest.tool_ids,
        manifest.document_ids,
        manifest.policy_ids,
        manifest.episode_ids,
    ):
        overlap = set(result).intersection(mapping)
        if overlap:
            raise ValueError(f"manifest source identifiers overlap: {sorted(overlap)}")
        result.update(mapping)
    return result


def _safe_document_path(path: str) -> PurePosixPath:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise CompletenessError(f"document path escapes bundle: {path}")
    if not normalized.parts or normalized.parts[0] != "documents":
        raise CompletenessError(f"document path must be under documents/: {path}")
    return normalized


def _referenced_ids(value: Any, known_ids: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        for identifier in known_ids:
            if identifier in value:
                found.add(identifier)
    elif isinstance(value, list):
        for item in value:
            found.update(_referenced_ids(item, known_ids))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.update(_referenced_ids(key, known_ids))
            found.update(_referenced_ids(item, known_ids))
    return found


def _explicit_references(value: Any) -> dict[str, set[str]]:
    references = {"agent": set(), "policy": set(), "tool": set(), "document": set()}
    key_kinds = {
        "agent_id": "agent", "agent_ids": "agent",
        "policy_id": "policy", "policy_ids": "policy",
        "tool_id": "tool", "tool_ids": "tool",
        "doc_id": "document", "doc_ids": "document",
        "document_id": "document", "document_ids": "document",
    }
    if isinstance(value, list):
        for item in value:
            child = _explicit_references(item)
            for kind, identifiers in child.items():
                references[kind].update(identifiers)
    elif isinstance(value, dict):
        for key, item in value.items():
            kind = key_kinds.get(str(key))
            if kind:
                if isinstance(item, str):
                    references[kind].add(item)
                elif isinstance(item, list):
                    references[kind].update(
                        identifier for identifier in item if isinstance(identifier, str)
                    )
            child = _explicit_references(item)
            for child_kind, identifiers in child.items():
                references[child_kind].update(identifiers)
    return references


def validate_completeness(
    metadata: EnvMetadata,
    trajectory: Trajectory,
    documents: Mapping[str, bytes],
    source_inventory: SourceInventory,
    manifest: SanitizeManifest,
) -> None:
    role_ids = {role.agent_id for role in metadata.roles}
    policy_ids = {policy.policy_id for policy in metadata.policies}
    tool_ids = {tool.tool_id for tool in metadata.tools}
    document_ids = {document.doc_id for document in metadata.documents}
    expected_roles = {
        manifest.agent_ids.get(identifier, identifier)
        for identifier in source_inventory.role_ids
    }
    expected_policies = {
        manifest.policy_ids.get(identifier, identifier)
        for identifier in source_inventory.policy_ids
    }
    expected_tools = {
        manifest.tool_ids.get(identifier, identifier)
        for identifier in source_inventory.tool_ids
    }
    expected_documents = {
        manifest.document_ids.get(identifier, identifier)
        for identifier in source_inventory.document_ids
    }
    if role_ids != expected_roles:
        raise CompletenessError(
            f"role inventory mismatch: expected={sorted(expected_roles)} actual={sorted(role_ids)}"
        )
    if policy_ids != expected_policies:
        raise CompletenessError(
            f"policy inventory mismatch: expected={sorted(expected_policies)} actual={sorted(policy_ids)}"
        )
    if tool_ids != expected_tools:
        raise CompletenessError(
            f"tool inventory mismatch: expected={sorted(expected_tools)} actual={sorted(tool_ids)}"
        )
    if document_ids != expected_documents:
        raise CompletenessError(
            f"document inventory mismatch: expected={sorted(expected_documents)} actual={sorted(document_ids)}"
        )

    expected_paths = set()
    for document in metadata.documents:
        path = _safe_document_path(document.path).as_posix()
        expected_paths.add(path)
        if path not in documents:
            raise CompletenessError(f"missing document content: {path}")
        if not documents[path]:
            raise CompletenessError(f"empty document content: {path}")
    extras = set(documents) - expected_paths
    if extras:
        raise CompletenessError(f"unlisted documents present: {sorted(extras)}")

    known_ids = role_ids | policy_ids | tool_ids | document_ids
    trajectory_data = trajectory.model_dump(mode="json")
    referenced = _referenced_ids(trajectory_data, known_ids)
    explicit = _explicit_references(trajectory_data)
    inventories = {
        "agent": role_ids,
        "policy": policy_ids,
        "tool": tool_ids,
        "document": document_ids,
    }
    for kind, identifiers in explicit.items():
        unresolved = identifiers - inventories[kind]
        if unresolved:
            raise CompletenessError(
                f"trajectory has unresolved {kind} references: {sorted(unresolved)}"
            )
    unresolved_participants = {
        participant
        for step in trajectory.steps
        for participant in (step.sender, step.receiver)
        if participant.startswith("agent_") and participant not in role_ids
    }
    if unresolved_participants:
        raise CompletenessError(
            f"trajectory has unresolved agents: {sorted(unresolved_participants)}"
        )
    unresolved_agents = set(trajectory.agents) - role_ids
    if unresolved_agents:
        raise CompletenessError(
            f"trajectory agent inventory is unresolved: {sorted(unresolved_agents)}"
        )
    if not referenced.issubset(known_ids):
        raise CompletenessError("trajectory contains unresolved identifiers")


def lint_leakage(
    named_payloads: Iterable[tuple[str, bytes]],
    denylist: Iterable[str] = DEFAULT_DENYLIST,
) -> None:
    violations: list[str] = []
    tokens = tuple(token for token in denylist if token)
    for name, payload in named_payloads:
        text = payload.decode("utf-8", errors="replace")
        for token in tokens:
            if re.search(re.escape(token), text, flags=re.IGNORECASE):
                violations.append(f"{name}: {token}")
    if violations:
        raise LeakageError("leakage denylist hits: " + "; ".join(sorted(violations)))


def sanitize_bundle(
    metadata: EnvMetadata,
    trajectory: Trajectory,
    documents: Mapping[str, bytes | str],
    manifest: SanitizeManifest,
    source_inventory: SourceInventory,
    denylist: Iterable[str] = DEFAULT_DENYLIST,
) -> SanitizedBundle:
    substitutions = _all_substitutions(manifest)
    metadata_data = _replace_value(metadata.model_dump(mode="json"), substitutions)
    trajectory_data = _replace_value(trajectory.model_dump(mode="json"), substitutions)
    trajectory_data["outcome"] = {
        key: value
        for key, value in trajectory_data["outcome"].items()
        if not RISK_OUTCOME_KEY.search(key)
    }
    for step in trajectory_data["steps"]:
        step["metadata"] = _clean_metadata(step["metadata"], substitutions)

    sanitized_metadata = EnvMetadata.model_validate(metadata_data)
    sanitized_trajectory = Trajectory.model_validate(trajectory_data)
    document_path_by_source_id = {
        document.doc_id: document.path for document in metadata.documents
    }
    sanitized_documents: dict[str, bytes] = {}
    for source_id, source_path in document_path_by_source_id.items():
        if source_path not in documents:
            raise CompletenessError(f"source document missing: {source_path}")
        sanitized_id = manifest.document_ids.get(source_id, source_id)
        suffix = PurePosixPath(source_path.replace("\\", "/")).suffix or ".txt"
        output_path = f"documents/{sanitized_id}{suffix}"
        content = documents[source_path]
        raw = content.encode("utf-8") if isinstance(content, str) else content
        sanitized_documents[output_path] = _replace_text(
            raw.decode("utf-8", errors="strict"), substitutions
        ).encode("utf-8")

    document_paths = {
        manifest.document_ids.get(document.doc_id, document.doc_id):
        f"documents/{manifest.document_ids.get(document.doc_id, document.doc_id)}"
        f"{PurePosixPath(document.path.replace('\\', '/')).suffix or '.txt'}"
        for document in metadata.documents
    }
    for document in sanitized_metadata.documents:
        document.path = document_paths[document.doc_id]

    validate_completeness(
        sanitized_metadata,
        sanitized_trajectory,
        sanitized_documents,
        source_inventory,
        manifest,
    )
    metadata_json = _canonical_json(sanitized_metadata.model_dump(mode="json"))
    trajectory_json = _canonical_json(sanitized_trajectory.model_dump(mode="json"))
    lint_leakage(
        [
            ("env_metadata.json", metadata_json),
            ("trajectory.json", trajectory_json),
            *sanitized_documents.items(),
        ],
        denylist,
    )
    return SanitizedBundle(
        metadata=sanitized_metadata,
        trajectory=sanitized_trajectory,
        documents=dict(sorted(sanitized_documents.items())),
    )


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
