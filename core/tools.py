"""Lightweight, secure tool helpers for local Termux execution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Iterable, Sequence, Union

CommandInput = Union[str, Sequence[str]]


class ToolExecutor:
    """Small wrapper around local subprocess and file access operations."""

    def __init__(self, allowed_commands: Iterable[str] | None = None):
        self.allowed_commands = {str(item) for item in (allowed_commands or [])}

    def normalize_command(self, command: CommandInput) -> list[str]:
        if isinstance(command, str):
            if not command.strip():
                raise ValueError("command cannot be empty")
            parts = command.split()
        else:
            parts = [str(part) for part in command]
        if not parts:
            raise ValueError("command cannot be empty")
        return parts

    def run_command(
        self,
        command: CommandInput,
        *,
        timeout: int = 30,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> dict[str, Any]:
        """Run a command without invoking a shell to reduce injection risk."""
        normalized = self.normalize_command(command)

        if self.allowed_commands:
            executable = Path(normalized[0]).name
            if executable not in self.allowed_commands:
                raise PermissionError(f"Command '{executable}' is not allowed")

        completed = subprocess.run(
            normalized,
            capture_output=True,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
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


def run_command(
    command: CommandInput,
    *,
    timeout: int = 30,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
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
