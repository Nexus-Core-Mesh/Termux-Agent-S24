"""Multi-step ReAct loop for the local Termux agent."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .memory import MemoryManager
from .tools import ToolExecutor, http_get


class TermuxAgent:
    """Lightweight local agent with a Reason-Act-Observe loop."""

    def __init__(
        self,
        workspace_dir: str | Path = "workspace",
        memory_path: str | Path | None = None,
        allowed_commands: list[str] | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
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
        safe_path = self.tools.safe_join(self.workspace_dir, str(Path(path))) if not str(path).startswith(str(self.workspace_dir)) else str(Path(path))
        content = self.tools.read_file(safe_path)
        self.memory.log_action("read_file", path=safe_path, length=len(content))
        return content

    def write_text(self, path: str | Path, content: str, *, append: bool = False) -> str:
        safe_path = self.tools.safe_join(self.workspace_dir, str(Path(path))) if not str(path).startswith(str(self.workspace_dir)) else str(Path(path))
        saved_path = self.tools.write_file(safe_path, content, append=append)
        self.memory.log_action("write_file", path=saved_path, append=append, length=len(content))
        return saved_path

    @staticmethod
    def split_subtasks(task: str) -> list[str]:
        cleaned = (task or "").strip()
        if not cleaned:
            return []
        normalized = re.sub(r"\s+", " ", cleaned)
        separator_pattern = r"\s*(?:;|\b(?:and\s+then|then|und\s+dann)\b)\s*"
        parts = [part.strip() for part in re.split(separator_pattern, normalized, flags=re.IGNORECASE) if part and part.strip()]
        return parts or [normalized]

    @staticmethod
    def _summarize_result(result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return "no result"
        payload = result.get("result", result)
        if not isinstance(payload, dict):
            return str(payload)[:120]
        status = "success" if payload.get("ok") or payload.get("returncode") == 0 or payload.get("status") == 200 else "failed"
        path = payload.get("path") or payload.get("file")
        entries = payload.get("entries")
        content = payload.get("content")
        if path:
            return f"{status}; path={path}"
        if entries:
            return f"{status}; entries={len(entries)}"
        if content:
            return f"{status}; content={str(content)[:80]}"
        return status

    def _extract_path(self, goal: str) -> str | None:
        goal_text = (goal or "").strip()
        if not goal_text:
            return str(self.workspace_dir)

        patterns = [
            r"(?:named|name|in|at|to|from)\s+([A-Za-z0-9_.\-/]+(?:/[A-Za-z0-9_.\-/]+)*\.[A-Za-z0-9]{1,10})",
            r"(?:workspace|~?/)?[A-Za-z0-9_.\-/]+(?:/[A-Za-z0-9_.\-/]+)*\.[A-Za-z0-9]{1,10}",
            r"(?:workspace|~?/)[A-Za-z0-9_.\-/]+",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, goal_text, flags=re.IGNORECASE)
            for candidate in matches:
                if not candidate:
                    continue
                cleaned = candidate.strip().strip('"\'')
                if any(marker in cleaned for marker in ("&&", "||", ";", "|", "\n", "\r")):
                    continue
                if cleaned.lower() in {"workspace", "file", "path", "location"}:
                    return str(self.workspace_dir)
                if cleaned.lower() == "workspace/":
                    return str(self.workspace_dir)
                try:
                    return self.tools.resolve_workspace_path(self.workspace_dir, cleaned)
                except ValueError:
                    continue
        return str(self.workspace_dir)

    def _extract_content(self, goal: str) -> str | None:
        match = re.search(r"(?:content|text|message)\s*[:=]\s*(.+)", goal, flags=re.IGNORECASE)
        if match:
            content = match.group(1).strip().strip('"\'')
            if content and not any(marker in content for marker in ("&&", "||", ";", "|", "\n", "\r")):
                return content
        if re.search(r"(?:write|create|save|generate)\s+(?:a\s+)?(?:file|text)\b", goal, flags=re.IGNORECASE):
            return f"Autonomous agent action for: {goal}"
        return None

    def _resolve_task_to_action(self, task: str) -> tuple[str, dict[str, Any]]:
        cleaned = (task or "").strip()
        if not cleaned:
            return "run_command", {"command": ["echo", "agent idle"]}

        lowered = cleaned.lower()
        if re.search(r"(write|create|save|generate|make).*file|file.*(write|create|save|generate|make)", lowered):
            path_match = re.search(r"(?:named|name|in)\s+([A-Za-z0-9_.\-/]+)", cleaned, flags=re.IGNORECASE)
            path_name = path_match.group(1) if path_match else "agent_task.txt"
            target = self.tools.safe_join(self.workspace_dir, path_name)
            content_match = re.search(r"(?:with\s+content|content|text|message)\s*[:=]?\s*(.+)$", cleaned, flags=re.IGNORECASE)
            content = (
                content_match.group(1).strip().strip('"\'')
                if content_match and content_match.group(1)
                else f"Task generated by TermuxAgent: {cleaned}\n"
            )
            return "write_file", {"path": target, "content": content}

        if re.search(r"(read|open|show|cat|inspect|view)\s+(?:file|the file|content)", lowered):
            path = self._extract_path(cleaned)
            return "read_file", {"path": path}

        if re.search(r"(list|ls|dir|show directory|workspace)", lowered):
            return "list_dir", {"path": str(self.workspace_dir)}

        if re.search(r"(http|https|api|fetch|request|url)", lowered):
            match = re.search(r"https?://\S+", cleaned)
            url = match.group(0) if match else "https://api.github.com"
            return "http_get", {"url": url, "expected_json": "json" in lowered or "api" in lowered}

        if re.search(r"(system|info|status|platform|uname)", lowered):
            return "system_info", {}

        return "run_command", {"command": ["echo", f"agent task: {cleaned}"]}

    def reason_about_goal(self, goal: str, last_result: dict[str, Any] | None = None) -> str:
        summary = [f"Goal: {goal}"]
        if last_result is None:
            summary.append("No previous observation; start with a targeted probe.")
            return " | ".join(summary)

        ok = bool(last_result.get("ok") or last_result.get("returncode") == 0 or last_result.get("status") == 200)
        if ok:
            summary.append("The previous action worked; continue with the next logical step.")
        else:
            summary.append("The previous action failed or was incomplete; revise the plan and retry with a safer step.")
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
        if re.search(r"(write|create|save|generate|make)", lowered):
            path = self._extract_path(goal) or str(self.workspace_dir / "agent_note.txt")
            content = self._extract_content(goal) or f"Autonomous agent action for: {goal}\n"
            return "write_file", {"path": path, "content": content}
        if re.search(r"(read|open|show|cat|inspect|view|file)", lowered):
            path = self._extract_path(goal) or str(self.workspace_dir / "notes.txt")
            return "read_file", {"path": path}
        if re.search(r"(list|ls|dir|workspace|directory)", lowered):
            return "list_dir", {"path": str(self.workspace_dir)}
        if re.search(r"(system|status|info|platform|uname)", lowered):
            return "system_info", {}
        if last_result and not (last_result.get("ok") or last_result.get("returncode") == 0):
            return "list_dir", {"path": str(self.workspace_dir)}
        return "run_command", {"command": ["echo", f"agent task: {goal}"]}

    def perform_action(self, action_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if action_name == "run_command":
            return self.execute_command(params["command"], timeout=params.get("timeout", 30))
        if action_name == "read_file":
            try:
                return {"ok": True, "content": self.tools.read_file(params["path"])}
            except FileNotFoundError:
                return {"ok": False, "error": f"File not found: {params['path']}"}
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

    def reflect_on_result(self, goal: str, result: dict[str, Any]) -> tuple[str, str | None, bool]:
        ok = bool(result.get("ok") or result.get("returncode") == 0 or result.get("status") == 200)
        if ok:
            if "http" in goal.lower() or "api" in goal.lower():
                return "Remote data retrieved successfully; the goal is likely satisfied or can continue from the result.", None, True
            if "write" in goal.lower() or "create" in goal.lower() or "save" in goal.lower():
                return "The write completed successfully; this task can be considered complete unless more follow-up work is needed.", None, True
            return "The action succeeded; continue with the next logical step if the task is not yet finished.", None, True

        if "read" in goal.lower() or "open" in goal.lower() or "file" in goal.lower():
            return "The file operation failed; verify whether the path exists and adjust the plan.", "inspect workspace files", False
        return "The previous step did not complete successfully; self-correct by trying a safer or more specific step.", "re-evaluate with a more precise action", False

    def _self_correct(self, goal: str, last_result: dict[str, Any] | None) -> str:
        if not last_result:
            return goal
        if not (last_result.get("ok") or last_result.get("returncode") == 0 or last_result.get("status") == 200):
            if "file" in goal.lower() or "write" in goal.lower() or "create" in goal.lower():
                return "inspect workspace files"
            if "http" in goal.lower() or "api" in goal.lower():
                return "check network availability and retry with a simpler request"
            return "review the previous output and retry with a smaller, safer action"
        return goal

    def run_once(self, task: str = "", command: str | list[str] | None = None) -> dict[str, Any]:
        if command is not None:
            payload: dict[str, Any] = {"status": "ok", "task": task}
            payload["result"] = self.execute_command(command)
            payload["status"] = "command_executed"
            self.memory.log_action("run_once", status=payload["status"], task=payload["task"], result=payload["result"])
            self.memory.update_state("last_run", payload)
            return payload

        task_text = (task or "").strip()
        if not task_text:
            return {"status": "empty_task", "task": task_text, "history": []}

        subtasks = self.split_subtasks(task_text)
        if len(subtasks) > 1:
            sequence_result = {
                "status": "completed",
                "goal": task_text,
                "subtasks": [],
                "history": [],
            }
            context_note = ""
            for idx, subtask in enumerate(subtasks, 1):
                sub_result = self.run_autonomous(subtask, max_cycles=5)
                sequence_result["subtasks"].append({"index": idx, "task": subtask, "result": sub_result})
                sequence_result["history"].extend(sub_result.get("history", []))
                context_note = f"Step {idx}: {subtask} -> {sub_result.get('status')}"
                self.memory.log_action("task_sequence_step", index=idx, task=subtask, status=sub_result.get("status"), context=context_note)
            self.memory.update_state("last_run", sequence_result)
            return sequence_result

        action_name, params = self._resolve_task_to_action(task_text)
        result = self.perform_action(action_name, params)
        payload = {
            "status": "executed",
            "task": task_text,
            "action": {"name": action_name, "params": params},
            "result": result,
        }
        self.memory.log_action("run_once", status=payload["status"], task=payload["task"], tool_action=payload["action"], result=payload["result"])
        self.memory.update_state("last_run", payload)
        return payload

    def _run_single_goal(self, goal: str, max_cycles: int = 5, prior_context: str = "") -> dict[str, Any]:
        if not goal or not goal.strip():
            return {"status": "empty_goal", "goal": goal, "cycles": 0, "history": []}

        self.memory.record_goal(goal)
        steps: list[dict[str, Any]] = []
        last_result: dict[str, Any] | None = None
        completed = False
        current_goal = goal.strip()

        for cycle in range(1, max_cycles + 1):
            thought = self.reason_about_goal(current_goal, last_result)
            if prior_context:
                thought = f"{prior_context} | {thought}"
            action_name, params = self.identify_action(current_goal, last_result)
            action = {"name": action_name, "params": params}
            result = self.perform_action(action_name, params)
            reflection, next_step, ok = self.reflect_on_result(current_goal, result)

            cycle_record = {
                "cycle": cycle,
                "goal": current_goal,
                "thought": thought,
                "action": action,
                "result": result,
                "reflection": reflection,
                "next_step": next_step,
                "completed": ok,
            }
            steps.append(cycle_record)
            self.memory.add_cycle(
                cycle=cycle,
                goal=current_goal,
                thought=thought,
                action=action,
                result=result,
                reflection=reflection,
                next_step=next_step,
            )
            last_result = result

            if ok and (next_step is None or not next_step.strip()):
                completed = True
                break

            if next_step:
                current_goal = next_step
                if not ok:
                    current_goal = self._self_correct(current_goal, result)
                continue

            if ok:
                completed = True
                break

        summary = {
            "status": "completed" if completed else "partial",
            "goal": goal,
            "max_cycles": max_cycles,
            "cycles": len(steps),
            "history": steps,
            "context": prior_context,
        }
        self.memory.update_state("last_autonomous_run", summary)
        return summary

    def run_autonomous(self, goal: str, max_cycles: int = 5) -> dict[str, Any]:
        task_text = (goal or "").strip()
        if not task_text:
            return {"status": "empty_goal", "goal": goal, "cycles": 0, "history": []}

        subtasks = self.split_subtasks(task_text)
        if len(subtasks) > 1:
            sequence_history: list[dict[str, Any]] = []
            combined: list[dict[str, Any]] = []
            prior_context = ""
            for idx, subtask in enumerate(subtasks, 1):
                previous = self._run_single_goal(subtask, max_cycles=max_cycles, prior_context=prior_context)
                combined.append({"index": idx, "task": subtask, "result": previous})
                sequence_history.extend(previous.get("history", []))
                prior_context = (
                    f"Completed subtask #{idx}: {subtask} ({previous.get('status')}) | "
                    f"last result: {self._summarize_result(previous)}"
                )
            return {
                "status": "completed",
                "goal": task_text,
                "subtasks": combined,
                "max_cycles": max_cycles,
                "cycles": sum(item["result"].get("cycles", 0) for item in combined),
                "history": sequence_history,
            }

        return self._run_single_goal(task_text, max_cycles=max_cycles)

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
