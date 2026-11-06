"""Optional local llama.cpp/Qwen integration for the Termux agent."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_LLAMA_CPP_DIR = Path.home() / "llama.cpp"
DEFAULT_QWEN_MODEL = Path.home() / "models" / "qwen2.5-coder-0.5b-instruct.gguf"
DEFAULT_LLAMA_SERVER_URL = "http://127.0.0.1:8081"


@dataclass
class LocalModelConfig:
    """Configuration for the optional local inference backend."""

    engine_path: str | None = None
    model_path: str | None = None
    binary_path: str | None = None
    server_url: str | None = None
    server_available: bool = False
    available: bool = False
    source: str = "fallback"


def _normalize_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    expanded = str(Path(str(value)).expanduser())
    return expanded if expanded and expanded != "." else None


def _probe_server(url: str) -> bool:
    try:
        request = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(request, timeout=2):
            return True
    except (urllib.error.URLError, TimeoutError, ValueError):
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=2):
                return True
        except (urllib.error.URLError, TimeoutError, ValueError):
            return False


def detect_local_llm_backend(
    engine_path: str | Path | None = None,
    model_path: str | Path | None = None,
    server_url: str | None = None,
) -> LocalModelConfig:
    """Discover a local llama.cpp backend and Qwen model on the device."""
    resolved_engine = _normalize_path(engine_path or DEFAULT_LLAMA_CPP_DIR)
    resolved_model = _normalize_path(model_path or DEFAULT_QWEN_MODEL)
    resolved_server = server_url or DEFAULT_LLAMA_SERVER_URL

    binary_candidates: list[str] = []
    if resolved_engine:
        engine_root = Path(resolved_engine)
        binary_candidates.extend(
            [
                str((engine_root / "llama-cli").resolve()),
                str((engine_root / "llama-server").resolve()),
                str((engine_root / "bin" / "llama-cli").resolve()),
                str((engine_root / "bin" / "llama-server").resolve()),
            ]
        )
    binary_candidates.extend([shutil.which("llama-cli") or "", shutil.which("llama-server") or ""])

    binary_path = None
    for candidate in binary_candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            binary_path = str(candidate_path)
            break

    model_exists = bool(resolved_model and Path(resolved_model).expanduser().exists() and Path(resolved_model).expanduser().is_file())
    server_available = model_exists and _probe_server(resolved_server)

    if server_available:
        source = "llama-server"
    elif model_exists and binary_path:
        source = "llama.cpp"
    else:
        source = "fallback"

    available = bool(model_exists and (server_available or binary_path))
    return LocalModelConfig(
        engine_path=resolved_engine,
        model_path=resolved_model if model_exists else None,
        binary_path=binary_path,
        server_url=resolved_server if server_available else None,
        server_available=server_available,
        available=available,
        source=source,
    )


class LocalLLMBackend:
    """Small, optional bridge to a local llama.cpp/Qwen backend."""

    def __init__(self, engine_path: str | Path | None = None, model_path: str | Path | None = None) -> None:
        self.config = detect_local_llm_backend(engine_path=engine_path, model_path=model_path)

    def is_available(self) -> bool:
        return bool(
            self.config.available
            and self.config.model_path
            and Path(self.config.model_path).expanduser().exists()
            and (self.config.server_available or self.config.binary_path)
        )

    def _fallback(self, prompt: str, *, reason: str | None = None) -> dict[str, Any]:
        message = reason or "Local llama.cpp backend unavailable; using deterministic local fallback behavior."
        return {
            "ok": True,
            "backend": "fallback",
            "source": "fallback",
            "available": False,
            "content": f"{message} Prompt: {prompt}",
        }

    def _call_llama_server(self, prompt: str, *, timeout: int, max_tokens: int, temperature: float) -> dict[str, Any]:
        if not self.config.server_available or not self.config.server_url:
            return {"ok": False, "error": "llama-server not available"}

        payload = {
            "model": Path(self.config.model_path).name if self.config.model_path else "qwen",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            f"{self.config.server_url}/v1/chat/completions",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8", errors="replace"))
                choices = body.get("choices") or []
                if choices:
                    message = choices[0].get("message", {})
                    content = message.get("content") or ""
                    if content:
                        return {
                            "ok": True,
                            "backend": "local",
                            "source": "llama-server",
                            "available": True,
                            "content": str(content).strip(),
                            "server_url": self.config.server_url,
                        }
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            pass

        return {"ok": False, "error": "llama-server responded without usable data"}

    def infer(
        self,
        prompt: str,
        *,
        timeout: int = 30,
        max_tokens: int = 128,
        temperature: float = 0.2,
        fallback: str | None = None,
    ) -> dict[str, Any]:
        """Run the local Qwen model through llama.cpp when available, else transparently fall back."""
        if not self.is_available():
            return self._fallback(prompt, reason=fallback or "Local llama.cpp backend unavailable; using deterministic local fallback behavior.")

        if self.config.server_available and self.config.server_url:
            server_result = self._call_llama_server(prompt, timeout=timeout, max_tokens=max_tokens, temperature=temperature)
            if server_result.get("ok"):
                return server_result

        if self.config.binary_path and self.config.model_path:
            command = [self.config.binary_path, "-m", self.config.model_path, "-p", prompt]
            if max_tokens:
                command.extend(["-n", str(max_tokens)])
            if temperature is not None:
                command.extend(["--temp", str(temperature)])

            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
            except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
                return {
                    "ok": False,
                    "backend": "local",
                    "source": "fallback",
                    "available": False,
                    "content": fallback or "Local llama.cpp backend failed; using deterministic local fallback behavior.",
                    "error": str(exc),
                }

            output = (completed.stdout or "").strip() or (completed.stderr or "").strip()
            if completed.returncode == 0 and output:
                return {
                    "ok": True,
                    "backend": "local",
                    "source": "llama.cpp",
                    "available": True,
                    "content": output,
                    "command": command,
                }

            return {
                "ok": False,
                "backend": "local",
                "source": "fallback",
                "available": False,
                "content": fallback or "Local llama.cpp backend failed; using deterministic local fallback behavior.",
                "stderr": completed.stderr,
                "stdout": completed.stdout,
                "returncode": completed.returncode,
            }

        return self._fallback(prompt, reason=fallback or "Local llama.cpp backend unavailable; using deterministic local fallback behavior.")


__all__ = ["LocalModelConfig", "LocalLLMBackend", "detect_local_llm_backend"]
