"""Lightweight, secure tool helpers for local Termux execution."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Union

CommandInput = Union[str, Sequence[str]]

DEFAULT_ALLOWED_COMMANDS = {
    "echo",
    "ls",
    "pwd",
    "uname",
    "df",
    "free",
    "id",
    "cat",
    "head",
    "tail",
    "stat",
    "find",
    "mkdir",
    "touch",
    "cp",
    "mv",
    "rm",
    "python",
    "python3",
}


class ToolExecutor:
    """Small wrapper around local subprocess and file access operations."""

    def __init__(self, allowed_commands: Iterable[str] | None = None):
        self.allowed_commands = {str(item).lower() for item in (allowed_commands or DEFAULT_ALLOWED_COMMANDS)}

    def normalize_command(self, command: CommandInput) -> list[str]:
        if isinstance(command, str):
            if not command.strip():
                raise ValueError("command cannot be empty")
            parts = shlex.split(command)
        else:
            parts = [str(part) for part in command]
        if not parts:
            raise ValueError("command cannot be empty")
        return parts

    def check_allowed(self, normalized: list[str]) -> None:
        if not self.allowed_commands:
            return
        executable = Path(normalized[0]).name.lower()
        if executable not in self.allowed_commands:
            raise PermissionError(f"Command '{executable}' is not allowed")

    def run_command(
        self,
        command: CommandInput,
        *,
        timeout: int = 30,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
    ) -> dict[str, Any]:
        """Run a command without invoking a shell to reduce injection risk."""
        normalized = self.normalize_command(command)
        self.check_allowed(normalized)

        completed = subprocess.run(
            normalized,
            capture_output=True,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            input=input_text,
            shell=False,
            text=True,
            timeout=timeout,
        )

        return {
            "command": normalized,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "ok": completed.returncode == 0,
        }

    def write_file(
        self,
        path: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
        make_dirs: bool = True,
        append: bool = False,
    ) -> str:
        file_path = Path(path)
        if make_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with file_path.open(mode, encoding=encoding) as handle:
            handle.write(content)
        return str(file_path)

    def read_file(self, path: str | Path, *, encoding: str = "utf-8") -> str:
        return Path(path).read_text(encoding=encoding)

    def path_exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def list_dir(self, path: str | Path) -> list[str]:
        candidate = Path(path)
        if not candidate.exists():
            return []
        if not candidate.is_dir():
            return []
        return sorted(item.name for item in candidate.iterdir())

    def get_file_info(self, path: str | Path) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.exists():
            return {"exists": False, "path": str(file_path)}
        stats = file_path.stat()
        return {
            "exists": True,
            "path": str(file_path),
            "size": stats.st_size,
            "is_dir": file_path.is_dir(),
            "modified": datetime.fromtimestamp(stats.st_mtime).isoformat(timespec="seconds"),
        }

    def system_info(self) -> dict[str, Any]:
        return {
            "platform": sys.platform,
            "python_version": sys.version.split()[0],
            "cwd": str(Path.cwd()),
        }

    def http_get(
        self,
        url: str,
        *,
        timeout: int = 15,
        headers: Mapping[str, str] | None = None,
        expected_json: bool = False,
    ) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=dict(headers or {"User-Agent": "TermuxAgent-S24/1.0"}))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
            body = json.loads(payload) if expected_json and payload else payload
            return {
                "url": url,
                "status": response.status,
                "ok": 200 <= response.status < 300,
                "content_type": response.headers.get_content_type(),
                "body": body,
            }


def run_command(
    command: CommandInput,
    *,
    timeout: int = 30,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    allowed_commands: Iterable[str] | None = None,
) -> dict[str, Any]:
    return ToolExecutor(allowed_commands=allowed_commands).run_command(
        command,
        timeout=timeout,
        cwd=cwd,
        env=env,
        input_text=input_text,
    )


def write_file(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
    make_dirs: bool = True,
    append: bool = False,
) -> str:
    return ToolExecutor().write_file(path, content, encoding=encoding, make_dirs=make_dirs, append=append)


def read_file(path: str | Path, *, encoding: str = "utf-8") -> str:
    return ToolExecutor().read_file(path, encoding=encoding)


def http_get(
    url: str,
    *,
    timeout: int = 15,
    headers: Mapping[str, str] | None = None,
    expected_json: bool = False,
) -> dict[str, Any]:
    return ToolExecutor().http_get(url, timeout=timeout, headers=headers, expected_json=expected_json)


def system_info() -> dict[str, Any]:
    return ToolExecutor().system_info()


def list_dir(path: str | Path) -> list[str]:
    return ToolExecutor().list_dir(path)


def get_file_info(path: str | Path) -> dict[str, Any]:
    return ToolExecutor().get_file_info(path)
