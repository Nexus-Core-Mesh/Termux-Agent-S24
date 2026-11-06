"""Local execution loop for the autonomous Termux agent."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .memory import MemoryManager
from .tools import ToolExecutor, http_get


class TermuxAgent:
    """Lightweight reactive agent that plans and executes actions step by step."""

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

    def reason_about_goal(self, goal: str, last_result: dict[str, Any] | None = None) -> str:
        summary = [f"Goal: {goal}"]
        if last_result is None:
            summary.append("No previous result; start with a targeted probe.")
            return " | ".join(summary)

        if isinstance(last_result, dict):
            status = last_result.get("ok") or (last_result.get("returncode") == 0)
            if status:
                summary.append("The previous action succeeded; continue with the next logical step.")
            else:
                summary.append("The previous action failed; revise the approach and try a safer fallback.")
            payload = last_result.get("stdout") or last_result.get("body") or last_result.get("stderr") or ""
            snippet = str(payload)[:180].replace("\n", " ")
            if snippet:
                summary.append(f"Observed output: {snippet}")
        return " | ".join(summary)

    def identify_action(self, goal: str, last_result: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        lowered = goal.lower()
        if re.search(r"(http|https|api|request|fetch|url|web)", lowered):
            match = re.search(r"https?://\S+", goal)
            url = match.group(0) if match else "https://api.github.com"
            return "http_get", {"url": url, "expected_json": "json" in lowered or "api" in lowered}
        if re.search(r"(read|open|show|cat|inspect|file)", lowered):
            path = self._extract_path(goal) or str(self.workspace_dir / "notes.txt")
            return "read_file", {"path": path}
        if re.search(r"(write|create|save|generate|make)", lowered):
            path = self._extract_path(goal) or str(self.workspace_dir / "agent_note.txt")
            content = self._extract_content(goal) or f"Autonomous agent action for: {goal}\n"
            return "write_file", {"path": path, "content": content}
        if re.search(r"(list|ls|dir|workspace|directory)", lowered):
            path = self._extract_path(goal) or str(self.workspace_dir)
            return "list_dir", {"path": path}
        if re.search(r"(system|status|info|platform|uname)", lowered):
            return "system_info", {}

        if last_result and not (last_result.get("ok") or last_result.get("returncode") == 0):
            return "list_dir", {"path": str(self.workspace_dir)}
        return "run_command", {"command": ["echo", f"agent task: {goal}"]}

    def _extract_path(self, goal: str) -> str | None:
        matches = re.findall(r"(?:[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,10}|~/[A-Za-z0-9_./-]+|/\S+)", goal)
        if matches:
            return matches[0].replace("~", str(Path.home()))
        return None

    def _extract_content(self, goal: str) -> str | None:
        match = re.search(r"(?:content|text|message)\s*[:=]\s*(.+)", goal, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def perform_action(self, action_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if action_name == "run_command":
            return self.execute_command(params["command"], timeout=params.get("timeout", 30))
        if action_name == "read_file":
            return {"ok": True, "content": self.tools.read_file(params["path"])}
        if action_name == "write_file":
            path = self.tools.write_file(params["path"], params["content"])
            return {"ok": True, "path": path, "bytes_written": len(params["content"])}
        if action_name == "list_dir":
            return {"ok": True, "entries": self.tools.list_dir(params["path"])}
        if action_name == "system_info":
            return {"ok": True, **self.tools.system_info()}
        if action_name == "http_get":
            return http_get(params["url"], timeout=params.get("timeout", 15), expected_json=params.get("expected_json", False))
        return {"ok": False, "error": f"Unknown action: {action_name}"}

    def reflect_on_result(self, goal: str, result: dict[str, Any]) -> tuple[str, str | None]:
        ok = bool(result.get("ok") or result.get("returncode") == 0 or result.get("status") == 200)
        if ok:
            if "http" in goal.lower() or "api" in goal.lower():
                return "Remote data was retrieved successfully; use the response to inform the next step.", None
            if "write" in goal.lower() or "create" in goal.lower() or "save" in goal.lower():
                return "The write operation completed; confirm the resulting file or continue with follow-up work.", None
            return "The action succeeded; continue with the next logical step toward the objective.", None

        if "read" in goal.lower() or "open" in goal.lower() or "file" in goal.lower():
            return "The file lookup failed; check whether the target path exists or is readable.", "inspect workspace files"
        return "The previous action did not succeed; retry with a safer or more specific command.", "re-evaluate with a simpler command"

    def _resolve_task_to_action(self, task: str) -> tuple[str, dict[str, Any]]:
        cleaned = (task or "").strip()
        if not cleaned:
            return "run_command", {"command": ["echo", "agent idle"]}

        goal = cleaned.lower()
        if re.search(r"(write|create|save|generate|make).*file|file.*(write|create|save|generate|make)", goal):
            match = re.search(r"(?:named|name)\s+([A-Za-z0-9_.-]+)", cleaned, flags=re.IGNORECASE)
            path = str(self.workspace_dir / (match.group(1) if match else "agent_task.txt"))
            content_match = re.search(r"with content\s*(.+)$|content\s*[:=]\s*(.+)$", cleaned, flags=re.IGNORECASE)
            content = content_match.group(1) if content_match and content_match.group(1) else content_match.group(2) if content_match else f"Task generated by TermuxAgent: {cleaned}\n"
            return "write_file", {"path": path, "content": content}

        if re.search(r"(read|open|show|cat|inspect)\s+(?:file|the file|content)", goal):
            path = self._extract_path(cleaned) or str(self.workspace_dir / "agent_task.txt")
            return "read_file", {"path": path}

        if re.search(r"(list|ls|dir|show directory|workspace)", goal):
            path = self._extract_path(cleaned) or str(self.workspace_dir)
            return "list_dir", {"path": path}

        if re.search(r"(http|https|api|fetch|request|url)", goal):
            match = re.search(r"https?://\S+", cleaned)
            url = match.group(0) if match else "https://api.github.com"
            return "http_get", {"url": url, "expected_json": "json" in goal or "api" in goal}

        if re.search(r"(system|info|status|platform|uname)", goal):
            return "system_info", {}

        return "run_command", {"command": ["echo", f"agent task: {cleaned}"]}

    def run_once(self, task: str = "", command: str | list[str] | None = None) -> dict[str, Any]:
        if command is not None:
            payload: dict[str, Any] = {"status": "ok", "task": task}
            payload["result"] = self.execute_command(command)
            payload["status"] = "command_executed"
            self.memory.log_action("run_once", **payload)
            self.memory.update_state("last_run", payload)
            return payload

        task_text = (task or "").strip()
        action_name, params = self._resolve_task_to_action(task_text)
        result = self.perform_action(action_name, params)

        payload = {
            "status": "executed",
            "task": task_text,
            "action": {"name": action_name, "params": params},
            "result": result,
        }
        self.memory.log_action("run_once", **payload)
        self.memory.update_state("last_run", payload)
        return payload

    def run_autonomous(self, goal: str, max_cycles: int = 5) -> dict[str, Any]:
        self.memory.record_goal(goal)
        steps: list[dict[str, Any]] = []
        last_result: dict[str, Any] | None = None

        for cycle in range(1, max_cycles + 1):
            thought = self.reason_about_goal(goal, last_result)
            action_name, params = self.identify_action(goal, last_result)
            action = {"name": action_name, "params": params}
            result = self.perform_action(action_name, params)
            reflection, next_step = self.reflect_on_result(goal, result)

            self.memory.add_cycle(
                cycle=cycle,
                goal=goal,
                thought=thought,
                action=action,
                result=result,
                reflection=reflection,
                next_step=next_step,
            )

            steps.append({"cycle": cycle, "thought": thought, "action": action, "result": result, "reflection": reflection})
            last_result = result

            if not next_step:
                break
            if cycle < max_cycles:
                goal = next_step

        summary = {"status": "completed", "goal": self.memory.get_state("current_goal"), "cycles": len(steps), "steps": steps}
        self.memory.update_state("last_autonomous_run", summary)
        return summary

    def run_loop(self, task: str = "", command: str | list[str] | None = None, max_cycles: int = 1) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for _ in range(max_cycles):
            result = self.run_once(task=task, command=command)
            results.append(result)
        summary = {"status": "completed", "cycles": len(results), "results": results}
        self.memory.update_state("last_loop", summary)
        return summary

    def status(self) -> dict[str, Any]:
        return {"workspace": str(self.workspace_dir), "state": self.memory.get_state(), "context": self.memory.get_recent_context()}
