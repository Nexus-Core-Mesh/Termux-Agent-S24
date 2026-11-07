"""Multi-step ReAct loop for the local Termux agent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .llm import LocalLLMBackend
from .memory import MemoryManager
from .tools import ToolExecutor, http_get


class TermuxAgent:
    """Lightweight local agent with a Reason-Act-Observe loop."""

    def __init__(
        self,
        workspace_dir: str | Path = "workspace",
        memory_path: str | Path | None = None,
        allowed_commands: list[str] | None = None,
        llm_backend: LocalLLMBackend | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.memory = MemoryManager(memory_path or self.workspace_dir / "memory.json")
        self.tools = ToolExecutor(allowed_commands=allowed_commands)
        self.llm_backend = llm_backend or LocalLLMBackend()
        self.memory.log_action("agent_initialized", workspace=str(self.workspace_dir), llm_backend=str(self.llm_backend.config.source))

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
        separator_pattern = (
            r"\s*(?:"
            r";|"
            r"\b(?:and\s+then|und\s+dann|then|dann)\b|"
            r",\s*(?=(?:and\s+)?(?:then|dann|read|write|create|save|generate|show|list|open|print|inspect|display|lies|lese|zeige|schreibe|erstelle|speichere|öffne|check|prüfe|view)\b)"
            r")\s*"
        )
        parts = [part.strip() for part in re.split(separator_pattern, normalized, flags=re.IGNORECASE) if part and part.strip()]
        if len(parts) > 1:
            flattened: list[str] = []
            for part in parts:
                flattened.extend(TermuxAgent.split_subtasks(part))
            return flattened
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

    def _get_latest_file_path(self) -> str | None:
        artifact_path = self.memory.get_latest_file_path()
        if artifact_path:
            return artifact_path

        for source in (self.memory.get_state("last_file_path"), self.memory.get_state("last_path")):
            if isinstance(source, str) and source.strip():
                return source.strip()

        history = self.memory.data.get("history", [])
        for item in reversed(history):
            action = item.get("action") if isinstance(item, dict) else {}
            if not isinstance(action, dict):
                continue
            result = item.get("result", {}) if isinstance(item, dict) else {}
            if isinstance(result, dict):
                path = result.get("path") or result.get("file")
                if isinstance(path, str) and path.strip():
                    return path.strip()
                if isinstance(action, dict):
                    params = action.get("params", {})
                    if isinstance(params, dict):
                        candidate = params.get("path")
                        if isinstance(candidate, str) and candidate.strip():
                            return candidate.strip()
        return None

    def _guarded_read_target(self, goal: str, explicit_path: str | None = None) -> str:
        if explicit_path:
            return explicit_path

        inherited = self._get_latest_file_path()
        if inherited:
            return inherited

        if "read it back" in goal.lower() or "read it" in goal.lower() or "read back" in goal.lower():
            return str(self.workspace_dir)

        return str(self.workspace_dir)

    def _extract_path(self, goal: str) -> str | None:
        goal_text = (goal or "").strip()
        if not goal_text:
            return str(self.workspace_dir)

        invalid_tokens = {
            "workspace", "file", "datei", "path", "location", "folder", "ordner", "verzeichnis",
            "named", "name", "called", "call", "in", "at", "to", "from", "of", "mit", "für",
        }

        patterns = [
            r"(?:named|name|called|in|at|to|from|of|mit|für|datei|file)\s+(?:the\s+)?([A-Za-z0-9_.\-/]+(?:/[A-Za-z0-9_.\-/]+)*(?:\.[A-Za-z0-9_.\-]+)?)",
            r"(?:workspace|~?/)?[A-Za-z0-9_.\-/]+(?:/[A-Za-z0-9_.\-/]+)*(?:\.[A-Za-z0-9_.\-]+)?",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, goal_text, flags=re.IGNORECASE)
            if not matches:
                continue
            for candidate in matches:
                cleaned = str(candidate).strip().strip('"\'')
                if not cleaned or any(marker in cleaned for marker in ("&&", "||", "|", "\n", "\r")):
                    continue
                lowered = cleaned.lower()
                if lowered in invalid_tokens:
                    continue
                if re.search(r"\b(?:and\s+then|then|und\s+dann|dann|read|write|create|save|show|list|open|inspect|print|display|file|datei|lies|lese|zeige|schreibe|erstelle|speichere|content|text|message|mit|inhalt)\b", lowered, flags=re.IGNORECASE):
                    continue
                if not ("/" in cleaned or cleaned.startswith("workspace") or cleaned.startswith("./") or cleaned.endswith((".txt", ".md", ".json", ".log", ".dat", ".csv"))):
                    if "." in cleaned and not cleaned.startswith("."):
                        pass
                    else:
                        continue
                try:
                    return self.tools.resolve_workspace_path(self.workspace_dir, cleaned)
                except ValueError:
                    continue

        fallback = re.search(r"workspace(?:/[A-Za-z0-9_.\-/]+)+", goal_text, flags=re.IGNORECASE)
        if fallback:
            try:
                return self.tools.resolve_workspace_path(self.workspace_dir, fallback.group(0))
            except ValueError:
                pass
        return str(self.workspace_dir)

    def _extract_content(self, goal: str) -> str | None:
        quoted = re.search(r"[\'\"]([^\'\"]+)[\'\"]", goal)
        if quoted:
            content = quoted.group(1).strip()
            if content and not any(marker in content for marker in ("&&", "||", "|", "\n", "\r")):
                return content

        match = re.search(r"(?:content|text|message|inhalt)\s*[:=]\s*(.+)", goal, flags=re.IGNORECASE)
        if match:
            content = match.group(1).strip().strip('"\'')
            if content and not any(marker in content for marker in ("&&", "||", "|", "\n", "\r")):
                return content

        content_after = re.search(r"(?:with\s+content|mit\s+content|content|text|message|inhalt)\s+(?:is\s+)?(.+?)(?:\s*(?:and\s+then|then|und\s+dann|dann|;|,\s*(?:read|write|create|save|generate|show|list|open|print|inspect|display|lies|lese|zeige|schreibe|erstelle|speichere)|$))", goal, flags=re.IGNORECASE)
        if content_after:
            candidate = content_after.group(1).strip().strip('"\'')
            if candidate and not any(marker in candidate for marker in ("&&", "||", "|", "\n", "\r")):
                return candidate

        if re.search(r"(?:write|create|save|generate|schreibe|erstelle|speichere)\s+(?:a\s+)?(?:file|text|datei)\b", goal, flags=re.IGNORECASE):
            return f"Autonomous agent action for: {goal}"
        return None

    @staticmethod
    def _extract_limit(goal: str) -> int | None:
        patterns = [
            r"(?:first|last|only|nur|ersten|letzten)\s+(?:the\s+)?(?:die\s+)?(\d+)\s+(?:chars?|characters|bytes?|zeichen)",
            r"(?:first|last|only|nur|ersten|letzten)\s+(?:the\s+)?(\d+)\s+(?:chars?|characters|bytes?|zeichen)",
        ]
        for pattern in patterns:
            match = re.search(pattern, goal, flags=re.IGNORECASE)
            if match:
                return max(0, int(match.group(1)))
        return None

    def _resolve_task_to_action(self, task: str) -> tuple[str, dict[str, Any]]:
        cleaned = (task or "").strip()
        if not cleaned:
            return "run_command", {"command": ["echo", "agent idle"]}

        lowered = cleaned.lower()
        slice_match = self._extract_limit(cleaned)
        limit = slice_match

        write_pattern = re.search(r"(?:write|create|save|generate|make|schreibe|schreiben|erstelle|erstellen|speichere|speichern|erzeuge|generiere)", lowered)
        read_pattern = re.search(r"(?:read|open|show|cat|inspect|view|list|lies|lese|zeige|anzeigen|ansehen|öffne|öffnen|liste)", lowered)
        file_like_hint = bool(re.search(r"(?:workspace/|\.[A-Za-z0-9]{1,8}\b|file\s+[A-Za-z0-9_.\-/]+|datei\s+[A-Za-z0-9_.\-/]+|in\s+workspace/[A-Za-z0-9_.\-/]+)", cleaned, flags=re.IGNORECASE))

        if write_pattern and ("file" in lowered or "datei" in lowered or "text" in lowered or "content" in lowered or "message" in lowered or file_like_hint):
            path_match = re.search(
                r"(?:file|datei)\s+(?:named|name|called|at|in|to|for|mit|für)?\s*(?:the\s+)?([A-Za-z0-9_.\-/]+(?:/[A-Za-z0-9_.\-/]+)*(?:\.[A-Za-z0-9_.\-]+)?)",
                cleaned,
                flags=re.IGNORECASE,
            )
            if not path_match:
                path_match = re.search(
                    r"(?:named|name|called|in|at|to|for|mit|für)\s+(?:the\s+)?([A-Za-z0-9_.\-/]+(?:/[A-Za-z0-9_.\-/]+)*(?:\.[A-Za-z0-9_.\-]+)?)",
                    cleaned,
                    flags=re.IGNORECASE,
                )
            if not path_match:
                path_match = re.search(r"workspace/[A-Za-z0-9_.\-/]+(?:\.[A-Za-z0-9_.\-]+)?", cleaned, flags=re.IGNORECASE)
            path_name = path_match.group(1) if path_match and path_match.groups() else (path_match.group(0) if path_match else "agent_task.txt")
            if path_name.lower() in {"file", "datei", "named", "name", "called", "in", "at", "to", "for", "mit", "für"}:
                path_name = "agent_task.txt"
            target = self.tools.safe_join(self.workspace_dir, path_name.replace("workspace/", "")) if path_name.startswith("workspace/") else self.tools.safe_join(self.workspace_dir, path_name)
            content_match = re.search(r"(?:with\s+content|mit\s+content|content|text|message|inhalt)\s*[:=]?\s*(.+?)(?:\s*(?:and\s+then|then|und\s+dann|dann|;|,\s*(?:read|write|create|save|generate|show|list|open|print|inspect|display|lies|lese|zeige|schreibe|erstelle|speichere))|$)", cleaned, flags=re.IGNORECASE)
            content = (
                content_match.group(1).strip().strip('"\'')
                if content_match and content_match.group(1)
                else f"Task generated by TermuxAgent: {cleaned}\n"
            )
            return "write_file", {"path": target, "content": content}

        if read_pattern and ("file" in lowered or "datei" in lowered or "workspace" in lowered or "content" in lowered or "read" in lowered or "lies" in lowered or "lese" in lowered or file_like_hint):
            inherited_path = self._get_latest_file_path()
            path = self._extract_path(cleaned) or inherited_path or str(self.workspace_dir)
            if ("read it back" in lowered or "read back" in lowered or "read it" in lowered or "lies it back" in lowered or "lies es zurück" in lowered) and inherited_path:
                path = inherited_path
            if limit is not None:
                return "read_file", {"path": path, "limit": limit}
            return "read_file", {"path": path}

        if re.search(r"(?:list|ls|dir|show directory|workspace|ordner|verzeichnis)", lowered) and not file_like_hint:
            return "list_dir", {"path": str(self.workspace_dir)}

        if re.search(r"(?:http|https|api|fetch|request|url)", lowered):
            match = re.search(r"https?://\S+", cleaned)
            url = match.group(0) if match else "https://api.github.com"
            return "http_get", {"url": url, "expected_json": "json" in lowered or "api" in lowered}

        if re.search(r"(?:system|info|status|platform|uname)", lowered):
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
            if isinstance(last_result, dict):
                error_message = last_result.get("error") or last_result.get("stderr") or last_result.get("body") or ""
                if isinstance(error_message, str) and "directory" in error_message.lower():
                    summary.append("FILE vs DIRECTORY RULE: use read_file only for files; use list_dir for directories. Never pass a directory path to read_file.")
                if isinstance(error_message, str) and any(token in error_message.lower() for token in ("syntaxerror", "traceback", "assert", "failed", "permission", "not found")):
                    summary.append("SELF-CORRECTION RULE: diagnose the exact failing operation, fix the likely root cause, and retry within the same cycle using a narrower, safer action.")
        payload = last_result.get("stdout") or last_result.get("body") or last_result.get("stderr") or ""
        snippet = str(payload)[:180].replace("\n", " ")
        if snippet:
            summary.append(f"Observed output: {snippet}")
        return " | ".join(summary)

    def identify_action(self, goal: str, last_result: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        lowered = goal.lower()
        limit = self._extract_limit(goal)

        if re.search(r"(?:show|print|display)\s+(?:only\s+)?(?:the\s+)?(?:first|last)\s+\d+\s+(?:chars?|characters|bytes?)", lowered):
            previous_content = None
            if isinstance(last_result, dict):
                previous_content = last_result.get("content") or last_result.get("stdout") or last_result.get("body")
                if isinstance(previous_content, dict):
                    previous_content = json.dumps(previous_content, ensure_ascii=False)
            if previous_content is None:
                previous_content = self.memory.get_state("last_content")
            if previous_content is None:
                previous_path = self.memory.get_state("last_file_path")
                if previous_path:
                    try:
                        previous_content = self.tools.read_file(previous_path)
                    except (FileNotFoundError, OSError):
                        previous_content = None
            if previous_content is not None:
                return "slice_output", {"text": str(previous_content), "limit": limit}

        if re.search(r"(http|https|api|request|fetch|url|web)", lowered):
            match = re.search(r"https?://\S+", goal)
            url = match.group(0) if match else "https://api.github.com"
            return "http_get", {"url": url, "expected_json": "json" in lowered or "api" in lowered}
        if re.search(r"(write|create|save|generate|make)", lowered):
            path = self._extract_path(goal) or str(self.workspace_dir / "agent_note.txt")
            content = self._extract_content(goal) or f"Autonomous agent action for: {goal}\n"
            return "write_file", {"path": path, "content": content}
        if re.search(r"(read|open|show|cat|inspect|view|file)", lowered):
            inherited_path = self._get_latest_file_path()
            path = self._extract_path(goal) or inherited_path
            if path is None:
                path = last_result.get("path") if isinstance(last_result, dict) else None
            if path is None:
                path = self.memory.get_state("last_file_path") or str(self.workspace_dir / "notes.txt")
            if ("read it back" in lowered or "read back" in lowered or "read it" in lowered or "lies it back" in lowered or "lies es zurück" in lowered) and inherited_path:
                path = inherited_path
            if path == str(self.workspace_dir) and re.search(r"(?:show|print|display)\s+(?:only\s+)?(?:the\s+)?(?:first|last)", lowered):
                previous_content = self.memory.get_state("last_content")
                if previous_content is not None:
                    return "slice_output", {"text": str(previous_content), "limit": limit}
            payload = {"path": path}
            if limit is not None:
                payload["limit"] = limit
            return "read_file", payload
        if re.search(r"(list|ls|dir|workspace|directory)", lowered):
            return "list_dir", {"path": str(self.workspace_dir)}
        if re.search(r"(system|status|info|platform|uname)", lowered):
            return "system_info", {}
        if re.search(r"(syntax|python|pytest|test|validate)", lowered):
            target_path = self._extract_path(goal) or self._get_latest_file_path() or str(self.workspace_dir)
            if "pytest" in lowered or "test" in lowered:
                return "run_pytest", {"path": target_path}
            return "validate_python_syntax", {"path": target_path}
        if last_result and not (last_result.get("ok") or last_result.get("returncode") == 0):
            if "directory" in str(last_result.get("error") or "").lower() or "read_file" in str(last_result.get("guidance") or "").lower():
                fallback_path = self._get_latest_file_path()
                if fallback_path:
                    return "read_file", {"path": fallback_path}
            return "list_dir", {"path": str(self.workspace_dir)}
        return "run_command", {"command": ["echo", f"agent task: {goal}"]}

    def perform_action(self, action_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if action_name == "run_command":
            return self.execute_command(params["command"], timeout=params.get("timeout", 30))
        if action_name == "read_file":
            path_value = params.get("path") or str(self.workspace_dir)
            try:
                if Path(path_value).is_dir():
                    fallback_path = self._get_latest_file_path()
                    if fallback_path:
                        self.memory.update_state("last_path", fallback_path)
                        self.memory.update_state("last_file_path", fallback_path)
                        return {
                            "ok": False,
                            "error": "Provided path is a directory. Use list_dir for directories or append the target filename.",
                            "fallback_path": fallback_path,
                            "guidance": "When a task asks to read back a file created previously, use the exact file path from the previous step's observation result. Never use read_file on a directory.",
                        }
                    return {
                        "ok": False,
                        "error": "Provided path is a directory. Use list_dir for directories or append the target filename.",
                        "guidance": "When a task asks to read back a file created previously, use the exact file path from the previous step's observation result. Never use read_file on a directory.",
                    }
                content = self.tools.read_file(path_value)
                self.memory.update_state("last_file_path", path_value)
                self.memory.update_state("last_path", path_value)
                self.memory.update_state("last_content", content)
                limit = params.get("limit")
                if limit is not None:
                    content = content[: int(limit)]
                return {"ok": True, "content": content}
            except FileNotFoundError:
                return {"ok": False, "error": f"File not found: {path_value}"}
            except (OSError, IsADirectoryError):
                return {"ok": False, "error": "Provided path is a directory. Use list_dir for directories or append the target filename.", "guidance": "When a task asks to read back a file created previously, use the exact file path from the previous step's observation result. Never use read_file on a directory."}
        if action_name == "slice_output":
            text = str(params.get("text", ""))
            limit = params.get("limit")
            if limit is not None:
                text = text[: int(limit)]
            self.memory.update_state("last_content", text)
            return {"ok": True, "content": text}
        if action_name == "write_file":
            path = self.tools.write_file(params["path"], params["content"])
            self.memory.update_state("last_file_path", path)
            self.memory.update_state("last_path", path)
            self.memory.update_state("last_content", params["content"])
            return {"ok": True, "path": path, "bytes_written": len(params["content"])}
        if action_name == "list_dir":
            return {"ok": True, "entries": self.tools.list_dir(params["path"])}
        if action_name == "system_info":
            return {"ok": True, **self.tools.system_info()}
        if action_name == "http_get":
            return http_get(params["url"], timeout=params.get("timeout", 15), expected_json=params.get("expected_json", False))
        if action_name == "validate_python_syntax":
            return self.tools.validate_python_syntax(params.get("path") or self.workspace_dir)
        if action_name == "run_pytest":
            return self.tools.run_pytest(params.get("path"), args=params.get("args"))
        return {"ok": False, "error": f"Unknown action: {action_name}"}

    def reflect_on_result(self, goal: str, result: dict[str, Any]) -> tuple[str, str | None, bool]:
        ok = bool(result.get("ok") or result.get("returncode") == 0 or result.get("status") == 200)
        if ok:
            if "http" in goal.lower() or "api" in goal.lower():
                return "Remote data retrieved successfully; the goal is likely satisfied or can continue from the result.", None, True
            if "write" in goal.lower() or "create" in goal.lower() or "save" in goal.lower():
                return "The write completed successfully; this task can be considered complete unless more follow-up work is needed.", None, True
            return "The action succeeded; continue with the next logical step if the task is not yet finished.", None, True

        error_text = str(result.get("error") or result.get("stderr") or result.get("body") or "").lower()
        if "read" in goal.lower() or "open" in goal.lower() or "file" in goal.lower():
            if "directory" in error_text:
                return "FILE vs DIRECTORY RULE: use read_file only for files; use list_dir for directories. Never pass a directory path to read_file. When a task asks to read back a file created previously, use the exact file path from the previous step's observation result.", "list workspace contents and then read the exact target file path from the previous step's result", False
            if any(token in error_text for token in ("syntaxerror", "traceback", "assert", "failed", "not found", "permission")):
                return "The file or tool operation failed; diagnose the exact issue, apply a surgical fix, and retry within the same cycle before escalating.", "narrow the failing operation to the precise file and retry with minimal context", False
            return "The file operation failed; verify whether the path exists and adjust the plan.", "inspect workspace files", False

        if any(token in error_text for token in ("syntaxerror", "traceback", "assert", "failed", "not found", "permission")):
            return "The previous action failed; adjust the strategy based on the exact traceback, then retry with a smaller and more targeted change.", "diagnose the failing step and apply the minimal corrective action", False
        return "The previous step did not complete successfully; self-correct by trying a safer or more specific step.", "re-evaluate with a more precise action", False

    def _self_correct(self, goal: str, last_result: dict[str, Any] | None) -> str:
        if not last_result:
            return goal

        error_text = str(last_result.get("error") or last_result.get("stderr") or last_result.get("body") or "").lower()
        if not (last_result.get("ok") or last_result.get("returncode") == 0 or last_result.get("status") == 200):
            if "directory" in error_text:
                fallback_path = self._get_latest_file_path()
                if fallback_path:
                    return f"read the exact file at {fallback_path}"
                return "list workspace contents and then read the exact target file"
            if "syntaxerror" in error_text or "traceback" in error_text or "assert" in error_text:
                return "fix the precise failing syntax or logic error and retry the same operation"
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

    def _run_single_goal(self, goal: str, max_cycles: int = 5, prior_context: str = "", initial_result: dict[str, Any] | None = None) -> dict[str, Any]:
        if not goal or not goal.strip():
            return {"status": "empty_goal", "goal": goal, "cycles": 0, "history": []}

        self.memory.record_goal(goal)
        steps: list[dict[str, Any]] = []
        last_result: dict[str, Any] | None = initial_result
        completed = False
        current_goal = goal.strip()

        for cycle in range(1, max_cycles + 1):
            thought = self.reason_about_goal(current_goal, last_result)
            if prior_context:
                thought = f"{prior_context} | {thought}"
            action_name, params = self.identify_action(current_goal, last_result)
            action = {"name": action_name, "params": params}
            result = self.perform_action(action_name, params)

            if not (result.get("ok") or result.get("returncode") == 0 or result.get("status") == 200):
                error_text = str(result.get("error") or result.get("stderr") or result.get("body") or "").lower()
                if "directory" in error_text:
                    fallback_path = self._get_latest_file_path()
                    if fallback_path:
                        params["path"] = fallback_path
                        result = self.perform_action(action_name, params)
                elif any(token in error_text for token in ("syntaxerror", "traceback", "assert", "not found", "permission", "failed")):
                    corrected_goal = self._self_correct(current_goal, result)
                    if corrected_goal and corrected_goal != current_goal:
                        current_goal = corrected_goal

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
            previous_result: dict[str, Any] | None = None
            for idx, subtask in enumerate(subtasks, 1):
                previous = self._run_single_goal(subtask, max_cycles=max_cycles, prior_context=prior_context, initial_result=previous_result)
                combined.append({"index": idx, "task": subtask, "result": previous})
                sequence_history.extend(previous.get("history", []))
                previous_result = previous.get("history", [{}])[-1].get("result") if previous.get("history") else previous
                prior_context = (
                    f"Completed subtask #{idx}: {subtask} ({previous.get('status')}) | "
                    f"last result: {self._summarize_result(previous_result or previous)}"
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

    def local_inference(
        self,
        prompt: str,
        *,
        timeout: int = 30,
        max_tokens: int = 128,
        temperature: float = 0.2,
        fallback: str | None = None,
    ) -> dict[str, Any]:
        if not prompt or not prompt.strip():
            return {"ok": False, "backend": self.llm_backend.config.source, "available": False, "content": "", "error": "empty prompt"}
        result = self.llm_backend.infer(
            prompt,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
            fallback=fallback,
        )
        self.memory.log_action("local_inference", prompt=prompt[:200], backend=result.get("backend"), available=result.get("available"), source=result.get("source"))
        return result

    def status(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace_dir),
            "state": self.memory.get_state(),
            "context": self.memory.get_recent_context(),
            "llm_backend": {
                "source": self.llm_backend.config.source,
                "available": self.llm_backend.is_available(),
                "binary_path": self.llm_backend.config.binary_path,
                "model_path": self.llm_backend.config.model_path,
            },
        }
