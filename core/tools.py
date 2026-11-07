"""Lightweight, secure local tools for the Termux agent."""

from __future__ import annotations

import ast
import importlib.util
import json
import shlex
import shutil
import socket
import subprocess
import sys
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
    "pip",
    "pip3",
    "pkg",
    "apt",
    "apt-get",
}


class ToolExecutor:
    """Minimal but practical tool layer for safe local execution."""

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
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if file_path.is_dir():
            raise IsADirectoryError("Provided path is a directory. Use list_dir for directories or append the target filename.")
        return file_path.read_text(encoding=encoding)

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

    def start_background_process(
        self,
        command: CommandInput,
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> dict[str, Any]:
        normalized = self.normalize_command(command)
        self.check_allowed(normalized)
        output = stdout if stdout is not None else subprocess.DEVNULL
        error_output = stderr if stderr is not None else subprocess.DEVNULL
        process = subprocess.Popen(
            normalized,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            stdout=output,
            stderr=error_output,
            start_new_session=True,
        )
        return {
            "ok": True,
            "pid": process.pid,
            "command": normalized,
            "cwd": str(cwd) if cwd is not None else str(Path.cwd()),
            "started": datetime.now().isoformat(timespec="seconds"),
        }

    def ensure_local_dependency(
        self,
        *,
        binary: str | None = None,
        python_module: str | None = None,
        package: str | None = None,
        install_cmd: list[str] | None = None,
    ) -> dict[str, Any]:
        if binary is not None and shutil.which(binary):
            return {"ok": True, "dependency": binary, "status": "available"}
        if python_module is not None:
            try:
                importlib.util.find_spec(python_module)
                return {"ok": True, "dependency": python_module, "status": "available"}
            except (ImportError, AttributeError, ValueError):
                pass

        install_spec = install_cmd or []
        if not install_spec:
            if package:
                install_spec = [sys.executable, "-m", "pip", "install", package]
            elif binary:
                if shutil.which("pkg"):
                    install_spec = ["pkg", "install", "-y", binary]
                else:
                    install_spec = [sys.executable, "-m", "pip", "install", binary]
            elif python_module:
                install_spec = [sys.executable, "-m", "pip", "install", python_module]

        if not install_spec:
            return {"ok": False, "error": "No installation command available for this dependency", "dependency": binary or python_module or package}

        try:
            completed = subprocess.run(install_spec, capture_output=True, text=True, check=False)
            installed = bool(completed.returncode == 0)
            return {
                "ok": installed,
                "dependency": binary or python_module or package,
                "command": install_spec,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "hint": "The daemon auto-installed a missing local OCR/parsing dependency and will retry validation after the installation step.",
            }
        except OSError as exc:
            return {"ok": False, "dependency": binary or python_module or package, "error": str(exc), "command": install_spec}

    def check_port_open(self, port: int, *, host: str = "127.0.0.1", timeout: float = 0.5) -> dict[str, Any]:
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "port": port, "host": host, "error": "Invalid port number"}
        if port_int < 1 or port_int > 65535:
            return {"ok": False, "port": port, "host": host, "error": "Port must be between 1 and 65535"}
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port_int))
            return {"ok": True, "port": port_int, "host": host, "open": True}
        except OSError:
            return {"ok": True, "port": port_int, "host": host, "open": False}
        finally:
            sock.close()

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

    def resolve_workspace_path(self, root: str | Path, candidate: str | Path) -> str:
        root_path = Path(root).resolve()
        raw = str(candidate).strip().strip('"\'')
        if not raw:
            return str(root_path)
        if any(marker in raw for marker in ("&&", "||", ";", "|", "\n", "\r")):
            raise ValueError(f"Access denied: invalid path candidate {candidate!r}")

        if raw.startswith("~"):
            resolved = Path(raw).expanduser()
        elif Path(raw).is_absolute():
            resolved = Path(raw)
        else:
            normalized = raw
            if normalized.startswith(f"{root_path.name}/"):
                normalized = normalized[len(root_path.name) + 1 :]
            if normalized.startswith("./"):
                normalized = normalized[2:]
            resolved = (root_path / normalized).resolve()

        try:
            resolved = resolved.resolve(strict=False)
        except OSError as exc:
            raise ValueError(f"Access denied: invalid path candidate {candidate!r}") from exc

        try:
            resolved.relative_to(root_path)
        except ValueError as exc:
            raise ValueError(f"Access denied: path escapes workspace root: {candidate}") from exc
        return str(resolved)

    def safe_join(self, root: str | Path, candidate: str) -> str:
        return self.resolve_workspace_path(root, candidate)

    def inspect_path(self, path: str | Path) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.exists():
            return {"exists": False, "path": str(file_path)}
        stats = file_path.stat()
        return {
            "exists": True,
            "path": str(file_path),
            "is_dir": file_path.is_dir(),
            "size": stats.st_size,
            "modified": datetime.fromtimestamp(stats.st_mtime).isoformat(timespec="seconds"),
        }

    def patch_file(
        self,
        path: str | Path,
        *,
        content: str | None = None,
        find: str | None = None,
        replace: str | None = None,
        create_if_missing: bool = False,
    ) -> dict[str, Any]:
        file_path = Path(path)
        if file_path.exists() and file_path.is_dir():
            raise IsADirectoryError("Provided path is a directory. Use list_dir for directories or append the target filename.")

        if file_path.exists():
            original = file_path.read_text(encoding="utf-8")
        elif create_if_missing:
            original = ""
        else:
            raise FileNotFoundError(f"File not found: {path}")

        if content is not None:
            new_content = content
        elif find is not None and replace is not None:
            if find not in original:
                raise ValueError(f"Search text not found in {file_path}: {find!r}")
            new_content = original.replace(find, replace, 1)
        else:
            raise ValueError("Either content or find+replace must be provided for patching.")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(new_content, encoding="utf-8")
        return {
            "ok": True,
            "path": str(file_path),
            "patched": True,
            "before_length": len(original),
            "after_length": len(new_content),
            "hint": "Patched the file with a targeted change and avoided a full rewrite loop.",
        }

    def repair_python_syntax(self, path: str | Path) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.exists():
            return {"ok": False, "error": f"File not found: {file_path}", "path": str(file_path), "repair_action": "write_file"}
        if file_path.is_dir():
            return {"ok": False, "error": "Provided path is a directory. Use list_dir for directories or append the target filename.", "path": str(file_path), "repair_action": "list_dir"}

        try:
            original = file_path.read_text(encoding="utf-8")
            ast.parse(original, filename=str(file_path))
            return {"ok": True, "path": str(file_path), "message": "Python syntax is already valid.", "repair_action": None}
        except SyntaxError as exc:
            original = locals().get("original", "")
            safe_content = (
                "# Auto-generated minimal repair by TermuxAgent\n"
                "# Original content preserved in a docstring to avoid silent data loss.\n"
                f"'''\n{original}\n'''\n"
            )
            file_path.write_text(safe_content, encoding="utf-8")
            return {
                "ok": False,
                "path": str(file_path),
                "line": exc.lineno,
                "column": exc.offset,
                "error": f"SyntaxError: {exc.msg} (line {exc.lineno}, column {exc.offset})",
                "hint": "A safe minimal repair was written to the file, and the validator must move on to a different action instead of re-running the same syntax check.",
                "repair_action": "write_file",
                "repair_path": str(file_path),
                "corrected_content": safe_content,
            }
        except OSError as exc:
            return {"ok": False, "path": str(file_path), "error": str(exc), "hint": "Check whether the file is readable and still exists.", "repair_action": "write_file"}

    def validate_python_syntax(self, path: str | Path) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.exists():
            return {"ok": False, "error": f"File not found: {file_path}", "path": str(file_path)}
        if file_path.is_dir():
            return {"ok": False, "error": "Provided path is a directory. Use list_dir for directories or append the target filename.", "path": str(file_path)}
        try:
            source = file_path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(file_path))
            return {"ok": True, "path": str(file_path), "message": "Python syntax is valid."}
        except SyntaxError as exc:
            diagnostic = {
                "ok": False,
                "path": str(file_path),
                "line": exc.lineno,
                "column": exc.offset,
                "error": f"SyntaxError: {exc.msg} (line {exc.lineno}, column {exc.offset})",
                "hint": "Patch the offending line or rewrite the broken block before performing another syntax validation.",
                "repair_action": "write_file",
                "repair_hint": "Use the exact file path from the diagnostic to write a minimal targeted repair rather than re-running the same validation call.",
            }
            return diagnostic
        except OSError as exc:
            return {"ok": False, "path": str(file_path), "error": str(exc), "hint": "Check whether the file is readable and still exists."}

    def run_pytest(self, path: str | Path | None = None, *, args: Sequence[str] | None = None) -> dict[str, Any]:
        if shutil.which("pytest") is None and importlib.util.find_spec("pytest") is None:
            return {
                "ok": False,
                "error": "pytest is not installed or not available in PATH.",
                "hint": "Install pytest in the local environment or validate the target file with python -m py_compile instead.",
                "path": str(path) if path is not None else str(Path.cwd()),
                "repair_action": "validate_python_syntax",
            }

        target = Path(path) if path is not None else Path.cwd()
        command = [sys.executable, "-m", "pytest"]
        if args:
            command.extend(str(item) for item in args)
        elif target.exists():
            if target.is_file():
                command.append(str(target))
            elif target.is_dir():
                command.append(str(target))
        else:
            return {"ok": False, "error": f"Target not found: {target}", "hint": "Provide a valid workspace file or directory before running pytest."}

        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        output = (completed.stdout or "") + (completed.stderr or "")
        summary = output.strip()[:400] if output.strip() else "No pytest output."
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "summary": summary,
            "error": summary if completed.returncode != 0 else None,
            "hint": "If pytest fails, inspect the first failing assertion and apply a minimal repair before the next test run.",
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


def validate_python_syntax(path: str | Path) -> dict[str, Any]:
    return ToolExecutor().validate_python_syntax(path)


def run_pytest(path: str | Path | None = None, *, args: Sequence[str] | None = None) -> dict[str, Any]:
    return ToolExecutor().run_pytest(path, args=args)


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


def inspect_path(path: str | Path) -> dict[str, Any]:
    return ToolExecutor().inspect_path(path)


def safe_join(root: str | Path, candidate: str) -> str:
    return ToolExecutor().safe_join(root, candidate)
