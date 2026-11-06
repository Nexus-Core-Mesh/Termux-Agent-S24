"""Optional local llama.cpp/Qwen integration for the Termux agent."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_LLAMA_CPP_DIR = Path.home() / "llama.cpp"
DEFAULT_QWEN_MODEL = Path.home() / "models" / "qwen2.5-coder-0.5b-instruct.gguf"


@dataclass
class LocalModelConfig:
    """Configuration for the optional local inference backend."""

    engine_path: str | None = None
    model_path: str | None = None
    binary_path: str | None = None
    available: bool = False
    source: str = "fallback"


def _normalize_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    expanded = str(Path(str(value)).expanduser())
    return expanded if expanded and expanded != "." else None


def detect_local_llm_backend(
    engine_path: str | Path | None = None,
    model_path: str | Path | None = None,
) -> LocalModelConfig:
    """Discover a local llama.cpp backend and Qwen model on the device."""
    resolved_engine = _normalize_path(engine_path or DEFAULT_LLAMA_CPP_DIR)
    resolved_model = _normalize_path(model_path or DEFAULT_QWEN_MODEL)

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
    available = bool(model_exists and binary_path)
    return LocalModelConfig(
        engine_path=resolved_engine,
        model_path=resolved_model if model_exists else None,
        binary_path=binary_path,
        available=available,
        source="local" if available else "fallback",
    )


class LocalLLMBackend:
    """Small, optional bridge to a local llama.cpp/Qwen backend."""

    def __init__(self, engine_path: str | Path | None = None, model_path: str | Path | None = None) -> None:
        self.config = detect_local_llm_backend(engine_path=engine_path, model_path=model_path)

    def is_available(self) -> bool:
        return bool(
            self.config.available
            and self.config.binary_path
            and self.config.model_path
            and Path(self.config.model_path).expanduser().exists()
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


__all__ = ["LocalModelConfig", "LocalLLMBackend", "detect_local_llm_backend"]
