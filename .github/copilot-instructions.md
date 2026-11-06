# Termux-Agent-S24 - Context & Guidelines

## Environment
- **Platform:** Android / Termux (aarch64)
- **Execution:** Runs locally on the S24 device.
- **Scope:** Independent, standalone repository located at `~/Termux-Agent-S24`. Isolated from the main Nexus-Core mesh infrastructure during development.

## Development Rules
- Keep code lightweight, modular, and optimized for local execution.
- Avoid heavy C-dependencies or packages that require complex compilation on mobile where possible.
- Use clean Python standard libraries or minimal dependencies.
