"""Process-local registry for globally ordered episode events."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class EpisodeEventRecorder:
    """Thread-safe append-only JSONL event recorder."""

    def __init__(self, path: Path, episode_id: str) -> None:
        self.path = path
        self.episode_id = episode_id
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._sequence = sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())
        else:
            self.path.touch()
            self._sequence = 0

    def append(
        self,
        event_type: str,
        *,
        agent_id: str | None = None,
        logical_step: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            event = {
                "event_seq": self._sequence,
                "episode_id": self.episode_id,
                "event_type": event_type,
                "agent_id": agent_id,
                "logical_step": logical_step,
                "payload": payload or {},
            }
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
            return event


_RECORDERS: dict[str, EpisodeEventRecorder] = {}
_REGISTRY_LOCK = threading.Lock()


def register_event_recorder(
    episode_id: str,
    episode_dir: Path,
) -> EpisodeEventRecorder:
    with _REGISTRY_LOCK:
        recorder = EpisodeEventRecorder(episode_dir / "events.jsonl", episode_id)
        _RECORDERS[episode_id] = recorder
        return recorder


def get_event_recorder(episode_id: str) -> EpisodeEventRecorder | None:
    with _REGISTRY_LOCK:
        return _RECORDERS.get(episode_id)
