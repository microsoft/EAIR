"""Environment-neutral episodes and a small conversational world runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm.client import LLMBackend, LLMResponse, MockLLMBackend
from risk_environments import CONFIRMED_RISKS
from verifier.exporter.export import export_bundle
from verifier.exporter.manifest import build_manifest
from verifier.exporter.sanitizer import SourceInventory
from verifier.schemas.env_metadata import EnvMetadata
from verifier.schemas.trajectory import Message, Trajectory


class WorldEpisode(BaseModel):
    """Adapter boundary for any orchestrator, independent of a risk taxonomy."""

    model_config = ConfigDict(extra="forbid")

    metadata: EnvMetadata
    trajectory: Trajectory
    documents: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source(self) -> "WorldEpisode":
        roles = {role.agent_id for role in self.metadata.roles}
        if set(self.trajectory.agents) != roles:
            raise ValueError("trajectory agents must exactly match metadata roles")
        expected = {document.path for document in self.metadata.documents}
        if set(self.documents) != expected:
            raise ValueError("document contents must exactly match the metadata inventory")
        for name in self.documents:
            path = PurePosixPath(name)
            if "\\" in name or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe document path: {name}")
            if len(path.parts) < 2 or path.parts[0] != "documents":
                raise ValueError("document paths must be beneath documents/")
        return self

    def write(self, destination: Path) -> Path:
        if destination.exists():
            raise FileExistsError(f"episode destination already exists: {destination}")
        destination.mkdir(parents=True)
        (destination / "episode.json").write_text(
            self.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return destination

    @classmethod
    def load(cls, source: Path) -> "WorldEpisode":
        path = source / "episode.json" if source.is_dir() else source
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender: str = Field(min_length=1)
    receiver: str = Field(min_length=1)
    channel: Literal[
        "handoff", "approval_request", "approval_decision", "summary", "policy_check", "chat"
    ] = "handoff"
    instruction: str = Field(min_length=1)
    mock_response: str = Field(min_length=1)


class WorldSpec(BaseModel):
    """An editable starter workflow; richer worlds implement WorldEpisode directly."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    world_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$")
    metadata: EnvMetadata
    task_spec: str = Field(min_length=1)
    turns: list[ConversationTurn] = Field(min_length=1)
    documents: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_world(self) -> "WorldSpec":
        if self.world_id in {*CONFIRMED_RISKS, "a1", "b1", "c1", "a2", "b2"}:
            raise ValueError("custom worlds must not shadow built-in or excluded risk IDs")
        if self.metadata.env_ref != self.world_id:
            raise ValueError("metadata.env_ref must match world_id")
        roles = {role.agent_id for role in self.metadata.roles}
        for turn in self.turns:
            if turn.sender not in roles:
                raise ValueError(f"unknown sending role: {turn.sender}")
            if turn.receiver not in roles and not turn.receiver.startswith("user:"):
                raise ValueError(f"unknown receiving role: {turn.receiver}")
        if self.metadata.tools:
            raise ValueError("the conversation starter cannot execute tools; use WorldEpisode for tool workflows")
        WorldEpisode(
            metadata=self.metadata,
            trajectory=Trajectory(
                episode_id="inventory-check", agents=sorted(roles),
                task_spec=self.task_spec, steps=[],
            ),
            documents=self.documents,
        )
        return self

    @classmethod
    def load(cls, source: Path) -> "WorldSpec":
        return cls.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


def run_conversation(
    spec: WorldSpec,
    episode_id: str,
    backend: LLMBackend | None = None,
    *,
    mock: bool = False,
    temperature: float = 0.0,
) -> WorldEpisode:
    if mock and backend is not None:
        raise ValueError("choose a real backend or mock mode, not both")
    if mock:
        backend = MockLLMBackend([
            LLMResponse(content=turn.mock_response) for turn in spec.turns
        ])
    if backend is None:
        raise ValueError("a model backend is required unless mock=True")
    roles = {role.agent_id: role for role in spec.metadata.roles}
    steps = [Message(
        step_id=f"{episode_id}.s0", t=0, sender="user:requester",
        receiver=spec.turns[0].sender, channel="handoff", content=spec.task_spec,
    )]
    for index, turn in enumerate(spec.turns, start=1):
        inbox = [
            {"sender": step.sender, "receiver": step.receiver, "content": step.content}
            for step in steps
            if turn.sender in {step.sender, step.receiver}
        ]
        documents = {
            document.doc_id: spec.documents[document.path]
            for document in spec.metadata.documents if turn.sender in document.acl
        }
        policies = [
            policy.text for policy in spec.metadata.policies
            if not policy.applies_to or turn.sender in policy.applies_to
        ]
        response = backend.chat(
            messages=[
                {"role": "system", "content": roles[turn.sender].system_prompt},
                {"role": "user", "content": json.dumps({
                    "task": spec.task_spec, "instruction": turn.instruction,
                    "inbox": inbox, "accessible_documents": documents,
                    "applicable_policies": policies,
                }, ensure_ascii=True)},
            ],
            tools=None,
            temperature=temperature,
        )
        if response.tool_calls:
            raise ValueError("conversation backend requested tools that this runner cannot execute")
        if not response.content or not response.content.strip():
            raise ValueError(f"empty model response from {turn.sender}")
        steps.append(Message(
            step_id=f"{episode_id}.s{index}", t=index, sender=turn.sender,
            receiver=turn.receiver, channel=turn.channel, content=response.content,
        ))
    return WorldEpisode(
        metadata=spec.metadata,
        trajectory=Trajectory(
            episode_id=episode_id, agents=list(roles), task_spec=spec.task_spec,
            steps=steps, outcome={"execution_mode": "mock" if mock else "live"},
        ),
        documents=spec.documents,
    )


def export_custom_episode(
    episode: WorldEpisode,
    bundles_root: Path,
    manifests_root: Path,
    sanitizer_version: str = "1",
) -> tuple[Path, Path]:
    manifest = build_manifest(episode.metadata, episode.trajectory, sanitizer_version)
    identity = hashlib.sha256(
        episode.model_dump_json().encode("utf-8") + b"\0" + sanitizer_version.encode("utf-8")
    ).hexdigest()[:20]
    bundle_dir = bundles_root / f"bundle_{identity}"
    manifest_path = manifests_root / f"bundle_{identity}.manifest.json"
    if manifests_root.resolve().is_relative_to(bundles_root.resolve()):
        raise ValueError("identity manifests must be outside the complete bundle store")
    if bundle_dir.exists() or manifest_path.exists():
        raise FileExistsError("this episode was already exported; use a new output store")
    inventory = SourceInventory(
        role_ids={role.agent_id for role in episode.metadata.roles},
        policy_ids={policy.policy_id for policy in episode.metadata.policies},
        tool_ids={tool.tool_id for tool in episode.metadata.tools},
        document_ids={document.doc_id for document in episode.metadata.documents},
    )
    export_bundle(
        bundle_dir, episode.metadata, episode.trajectory, episode.documents,
        manifest, inventory,
    )
    manifests_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return bundle_dir, manifest_path