"""Persistent JSON-backed memory for the local Termux agent."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MemoryManager:
    """Structured local memory store for goals, actions, and long-running context."""

    def __init__(self, memory_path: str | Path = "workspace/memory.json"):
        self.memory_path = Path(memory_path)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_state(self) -> dict[str, Any]:
        now = self._now_iso()
        return {
            "schema_version": "1.1",
            "created_at": now,
            "updated_at": now,
            "status": "initialized",
            "goals": [],
            "state": {},
            "history": [],
            "actions": [],
            "artifacts": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.memory_path.exists():
            fresh = self._default_state()
            self._save(fresh)
            return fresh

        with self.memory_path.open("r", encoding="utf-8") as handle:
            try:
                raw_data = json.load(handle)
            except json.JSONDecodeError:
                raw_data = {}

        if not isinstance(raw_data, dict):
            raw_data = {}

        normalized = self._default_state()
        for key in ("state", "goals", "history", "actions", "artifacts"):
            if isinstance(raw_data.get(key), type(normalized[key])):
                normalized[key] = raw_data[key]
        normalized["status"] = str(raw_data.get("status", "initialized"))
        normalized["updated_at"] = str(raw_data.get("updated_at", normalized["updated_at"]))
        return normalized

    def _save(self, data: dict[str, Any]) -> dict[str, Any]:
        data["updated_at"] = self._now_iso()
        with self.memory_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        self.data = data
        return data

    def save(self) -> dict[str, Any]:
        return self._save(self.data)

    def record_goal(self, goal: str, **details: Any) -> dict[str, Any]:
        entry = {
            "goal": goal,
            "status": "active",
            "created_at": self._now_iso(),
            "details": details,
        }
        existing = self.data.setdefault("goals", [])
        existing.append(entry)
        self.update_state("current_goal", goal)
        self.save()
        return entry

    def log_action(self, action: str, **details: Any) -> dict[str, Any]:
        entry = {
            "id": len(self.data.setdefault("actions", [])) + 1,
            "action": action,
            "timestamp": self._now_iso(),
            "details": details,
        }
        self.data["actions"].append(entry)
        self.save()
        return entry

    def add_cycle(
        self,
        *,
        cycle: int,
        goal: str,
        thought: str,
        action: dict[str, Any],
        result: dict[str, Any],
        reflection: str,
        next_step: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "cycle": cycle,
            "goal": goal,
            "thought": thought,
            "action": action,
            "result": result,
            "reflection": reflection,
            "next_step": next_step,
            "timestamp": self._now_iso(),
        }
        history = self.data.setdefault("history", [])
        if len(history) > 12:
            history[:] = history[-12:]
        history.append(entry)
        self.update_state("last_cycle", cycle)
        self.update_state("last_reflection", reflection)
        self.update_state("next_step", next_step)
        self._store_artifact_reference(goal, action, result)
        self.save()
        return entry

    def _store_artifact_reference(self, goal: str, action: dict[str, Any], result: dict[str, Any]) -> None:
        action_name = str((action or {}).get("name", ""))
        params = (action or {}).get("params", {}) if isinstance(action, dict) else {}
        path_value = None
        if isinstance(params, dict):
            path_value = params.get("path")
        if isinstance(result, dict):
            result_path = result.get("path")
            if isinstance(result_path, str) and result_path.strip():
                path_value = result_path
        if not isinstance(path_value, str) or not path_value.strip():
            return

        artifacts = self.data.setdefault("artifacts", {})
        if not isinstance(artifacts, dict):
            artifacts = {}
        artifacts["last_path"] = path_value.strip()
        artifacts["last_goal"] = goal.strip()
        artifacts["last_action"] = action_name
        self.data["artifacts"] = artifacts

    def update_state(self, key: str, value: Any) -> Any:
        self.data.setdefault("state", {})[key] = value
        self.save()
        return value

    def get_state(self, key: str | None = None) -> Any:
        state = self.data.get("state", {})
        if key is None:
            return state
        return state.get(key)

    def get_recent_context(self, limit: int = 5) -> dict[str, Any]:
        history = self.data.get("history", [])
        return {
            "current_goal": self.get_state("current_goal"),
            "last_reflection": self.get_state("last_reflection"),
            "next_step": self.get_state("next_step"),
            "recent_history": history[-limit:],
            "artifacts": self.data.get("artifacts", {}),
        }

    def get_latest_file_path(self) -> str | None:
        artifact_path = self.data.get("artifacts", {}).get("last_path")
        if isinstance(artifact_path, str) and artifact_path.strip():
            return artifact_path.strip()
        for key in ("last_file_path", "last_path"):
            value = self.get_state(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def reset(self) -> dict[str, Any]:
        fresh = self._default_state()
        self.data = fresh
        return self._save(fresh)
