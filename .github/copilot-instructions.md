# Termux-Agent-S24 - Context & Guidelines

## Environment
- **Platform:** Android / Termux (aarch64)
- **Execution:** Runs locally on the S24 device.
- **Scope:** Independent, standalone repository located at `~/Termux-Agent-S24`. Isolated from the main Nexus-Core mesh infrastructure during development.

## Architecture & Safety Model
- Keep the project lightweight, modular, and optimized for local execution.
- Prefer pure Python stdlib patterns over heavy native dependencies or cloud orchestration.
- Maintain strict workspace sandboxing: all local reads/writes must remain inside the repository workspace.
- Block path escapes such as `/etc/passwd`, `/sdcard`, or other absolute paths outside the agent workspace.
- Treat validation failures as deterministic state-machine transitions, not open-ended retry loops.
- When a `SyntaxError` occurs, force a surgical repair path with a minimal file write instead of repeating the same validation call blindly.
- Keep memory persistence in `workspace/memory.json` for long-running task context, action history, and repair records.

## Development Rules
- Avoid heavy C-dependencies or packages that require complex compilation on mobile where possible.
- Use clean Python standard libraries or minimal dependencies.
- Keep background local process helpers lightweight and non-invasive; prefer local port checks and sandboxed subprocess execution over remote network calls.
- Ensure direct file operations remain deterministic and workspace-local.
- Favor targeted edits and targeted repairs over rewriting whole scripts from scratch.
