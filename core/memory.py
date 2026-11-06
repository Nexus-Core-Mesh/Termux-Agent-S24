"""Persistent JSON-backed memory for the local Termux agent."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MemoryManager:
    """Simple local memory store for agent state and action history."""

    def __init__(self, memory_path: str | Path = "workspace/memory.json"):
        self.memory_path = Path(memory_path)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _default_state(self) -> dict[str, Any]:
        return {"state": {}, "actions": []}

    def _load(self) -> dict[str, Any]:
        if not self.memory_path.exists():
            self._save(self._default_state())
            return self._default_state()

        with self.memory_path.open("r", encoding="utf-8") as handle:
            try:
                raw_data = json.load(handle)
            except json.JSONDecodeError:
                raw_data = {}

        if not isinstance(raw_data, dict):
            raw_data = {}

        normalized = self._default_state()
        normalized["state"] = raw_data.get("state", {}) if isinstance(raw_data.get("state", {}), dict) else {}
        normalized["actions"] = raw_data.get("actions", []) if isinstance(raw_data.get("actions", []), list) else []
        return normalized

    def _save(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.memory_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        self.data = data
        return data

    def save(self) -> dict[str, Any]:
        return self._save(self.data)

    def log_action(self, action: str, **details: Any) -> dict[str, Any]:
        entry = {
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details,
        }
        self.data.setdefault("actions", []).append(entry)
        self.save()
        return entry

    def update_state(self, key: str, value: Any) -> Any:
        self.data.setdefault("state", {})[key] = value
        self.save()
        return value

    def get_state(self, key: str | None = None) -> Any:
        if key is None:
            return self.data.get("state", {})
        return self.data.get("state", {}).get(key)

    def reset(self) -> dict[str, Any]:
        fresh = self._default_state()
        self.data = fresh
        return self._save(fresh)
