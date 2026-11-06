"""Local execution loop for the autonomous Termux agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .memory import MemoryManager
from .tools import ToolExecutor


class TermuxAgent:
    """Lightweight agent that combines tool execution with local JSON memory."""

    def __init__(
        self,
        workspace_dir: str | Path = "workspace",
        memory_path: str | Path | None = None,
        allowed_commands: list[str] | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        self.memory = MemoryManager(memory_path or self.workspace_dir / "memory.json")
        self.tools = ToolExecutor(allowed_commands=allowed_commands)
        self.memory.log_action("agent_initialized", workspace=str(self.workspace_dir))

    def execute_command(
        self,
        command: str | list[str],
        *,
        timeout: int = 30,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.memory.log_action("command_started", command=command)
        result = self.tools.run_command(command, timeout=timeout, cwd=self.workspace_dir, **kwargs)
        self.memory.update_state("last_command", result)
        return result

    def read_text(self, path: str | Path) -> str:
        content = self.tools.read_file(path)
        self.memory.log_action("read_file", path=str(path), length=len(content))
        return content

    def write_text(self, path: str | Path, content: str, *, append: bool = False) -> str:
        saved_path = self.tools.write_file(path, content, append=append)
        self.memory.log_action("write_file", path=str(path), append=append, length=len(content))
        return saved_path

    def run_once(self, task: str = "", command: str | list[str] | None = None) -> dict[str, Any]:
        payload = {"status": "ok", "task": task}
        if command:
            payload["result"] = self.execute_command(command)
            payload["status"] = "command_executed"
        else:
            payload["result"] = {"status": "idle", "task": task}

        self.memory.log_action("run_once", **payload)
        self.memory.update_state("last_run", payload)
        return payload

    def run_loop(self, task: str = "", command: str | list[str] | None = None, max_cycles: int = 1) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for _ in range(max_cycles):
            result = self.run_once(task=task, command=command)
            results.append(result)
        summary = {"status": "completed", "cycles": len(results), "results": results}
        self.memory.update_state("last_loop", summary)
        return summary

    def status(self) -> dict[str, Any]:
        return {"workspace": str(self.workspace_dir), "state": self.memory.get_state()}
