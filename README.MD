# Termux-Agent-S24

A lightweight autonomous local agent for Android/Termux on aarch64 devices. The project is intentionally small, modular and dependency-light so it runs cleanly on a phone or emulator without requiring a heavy cloud stack.

## Overview

This repository contains a minimal local agent architecture with:

- a secure tool layer for local commands, file operations and light HTTP requests
- a JSON-backed memory manager for persistence across cycles
- a lightweight ReAct-style agent loop with reason, act, observe and self-correction
- a simple CLI entrypoint for direct task execution from the terminal

## Structure

- `core/tools.py` — safe subprocess execution, file read/write helpers, directory inspection and lightweight HTTP access
- `core/memory.py` — persistent workspace memory in `workspace/memory.json`
- `core/agent.py` — autonomous execution loop and task resolution logic
- `main.py` — interactive and one-shot CLI entrypoint
- `workspace/` — local runtime data and memory files

## Quick start

Run the agent interactively:

```bash
python main.py
```

Then enter tasks such as:

- `create a test file in workspace named test.txt with content hello from agent`
- `list workspace`
- `read file workspace/test.txt`

Run a single task without interactive input:

```bash
python main.py --task "create a test file in workspace named test.txt with content hello from agent"
```

## Design goals

- low dependency footprint
- deterministic local execution
- safe file and command handling
- persistent JSON memory for short- and medium-term context
- simple behaviour that remains easy to understand and extend on Termux

## Notes

The agent is intentionally conservative. It does not depend on a remote orchestrator, cloud runtime or heavy AI framework. It is designed to be useful as a local autonomous assistant for small, scriptable tasks on the device itself.
