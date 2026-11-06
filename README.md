# Termux-Agent-S24

A lightweight local autonomous agent for Android/Termux on aarch64 devices. It is intentionally small, modular and dependency-light so it runs smoothly on a phone or emulator without requiring a heavy cloud stack.

## Overview

This repository provides a compact local agent architecture with:

- a secure tool layer for local subprocess execution, file operations and lightweight HTTP requests
- a JSON-backed memory manager for keeping persistent state and execution history in `workspace/memory.json`
- a ReAct-style execution loop with reasoning, action execution, observation and self-correction
- a simple CLI entrypoint for one-shot and interactive task execution
- an optional local LLM bridge for llama.cpp and Qwen on the device, with a transparent fallback when local inference is unavailable

## Project structure

- `core/tools.py` — safe subprocess execution, path validation, file read/write helpers and lightweight HTTP access
- `core/memory.py` — persistent workspace memory and action history storage
- `core/agent.py` — task parsing, multi-step execution loop and autonomous decision logic
- `core/llm.py` — optional local llama.cpp / llama-server + Qwen detection and bridge support with clean fallback behavior
- `main.py` — interactive and direct task CLI entrypoint
- `workspace/` — local runtime state, memory and generated artifacts

## Quick start

Run the agent interactively:

```bash
python main.py
```

Then enter tasks such as:

- `create a file in workspace named notes.txt with content hello and then list workspace`
- `list workspace`
- `read file workspace/notes.txt`

Run a single task directly from the terminal:

```bash
python main.py --task "create a file in workspace named notes.txt with content hello and then list workspace"
```

## Design goals

- low dependency footprint
- deterministic local execution
- safe workspace-only file handling
- robust parsing of compound instructions with separators such as `and then`, `und dann` and `;`
- persistent JSON memory for multi-step context and task history
- simple implementation that remains easy to debug and extend on Termux

## Notes

The agent remains intentionally conservative: no remote orchestrator, cloud runtime or heavy ML framework is required. It is designed to perform useful local, scriptable work on the device itself while staying lightweight and resilient.
