# Termux-Agent-S24

A lightweight local autonomous agent for Android/Termux on aarch64 devices. It is intentionally small, modular and dependency-light so it runs smoothly on a phone or emulator without requiring a heavy cloud stack.

## Overview

This repository provides a compact local agent architecture designed specifically for Android/Termux on aarch64 devices. It stays intentionally small, modular and dependency-light while enforcing deterministic behavior around file access, validation, recovery, and memory continuity.

Key capabilities include:

- a secure tool layer for local subprocess execution, workspace file operations, syntax validation and a minimal background-process helper set
- a JSON-backed memory manager that persists runtime state in `workspace/memory.json`
- a ReAct-style execution loop with reasoning, action execution, observation and explicit self-correction guardrails
- deterministic repair flows that convert failed syntax validation into surgical write_file actions instead of blind retries
- strict workspace-only path enforcement and cleared access-denied responses for forbidden system paths
- an optional local LLM bridge for llama.cpp and Qwen on the device, with transparent fallback behavior when local inference is unavailable
- a local watchdog daemon that polls default download/storage areas and the project inbox for dropped files and automatically ingests them into the appropriate workspace project

## Project structure

- `core/tools.py` — safe subprocess execution, path validation, file read/write helpers, syntax validation, pytest checks, background process hooks and local port monitoring
- `core/memory.py` — persistent workspace memory and action history storage
- `core/agent.py` — task parsing, multi-step execution loop, guardrails, self-healing, and deterministic validation flow
- `core/llm.py` — optional local llama.cpp / llama-server + Qwen detection and bridge support with clean fallback behavior
- `core/watcher.py` — inbox-oriented drop-in daemon for local text/PDF/image ingestion
- `core/watchdog_daemon.py` — background watcher for storage/download roots plus the workspace inbox, routing drops into the correct project directory
- `main.py` — interactive and direct task CLI entrypoint
- `workspace/` — local runtime state, memory and generated artifacts

## Deterministic recovery model

The agent now treats validation and read failures as state-machine events rather than open-ended retries:

- missing file reads abort with a diagnostic instead of repeating the same missing-file call
- workspace escapes like `/etc/passwd` are rejected with an access-denied error
- syntax failures produce structured diagnostics including the exact line and description, then trigger a minimal file repair rather than another identical validation probe
- repeated validation calls with the same failing parameters are blocked and corrected with a surgical write action
- pytest failures are surfaced as clean structured results when the dependency is not available

## Quick start

Run the agent interactively:

```bash
python main.py
```

Then enter tasks such as:

- `create a file in workspace named notes.txt with content hello and then list workspace`
- `list workspace`
- `read file workspace/notes.txt`
- `validate python syntax for workspace/notes.py`

Run a single task directly from the terminal:

```bash
python main.py --task "create a file in workspace named notes.txt with content hello and then list workspace"
```

## Design goals

- low dependency footprint
- deterministic local execution under aarch64 / Termux constraints
- strict workspace-only file handling and sandbox safety
- robust parsing of compound instructions with separators such as `and then`, `und dann` and `;`
- persistent JSON memory for multi-step context and task history
- simple implementation that remains easy to debug and extend on Termux

## Notes

The agent remains intentionally conservative: no remote orchestrator, cloud runtime or heavy ML framework is required. It is designed to perform useful local, scriptable work on the device itself while staying lightweight, resilient, and deterministic.
