"""Core package for the lightweight local Termux agent."""

from .agent import TermuxAgent
from .llm import LocalLLMBackend, LocalModelConfig, detect_local_llm_backend
from .memory import MemoryManager
from .tools import ToolExecutor, read_file, run_command, write_file
from .watcher import DropInDaemon
from .watchdog_daemon import WatchdogDaemon

__all__ = [
    "TermuxAgent",
    "MemoryManager",
    "ToolExecutor",
    "LocalLLMBackend",
    "LocalModelConfig",
    "detect_local_llm_backend",
    "run_command",
    "read_file",
    "write_file",
    "DropInDaemon",
    "WatchdogDaemon",
]
