# Changelog

All notable updates for the Termux-Agent-S24 project.

## [Unreleased]

### Added
- Added deterministic self-healing around validation failures, including structured SyntaxError diagnostics and forced write_file repair actions instead of blind re-validation.
- Added workspace-safe path validation that blocks command chains and keeps file paths inside the repository workspace.
- Added a direct `--task` execution flow that triggers real autonomous behavior instead of idle output.
- Added local background-process hooks and a port-open probe to support simple local runtime orchestration without cloud dependencies.
- Added an optional local inference bridge in `core/llm.py` for local llama.cpp / llama-server access to Qwen models like `qwen2.5-coder-0.5b-instruct.gguf`.
- Added a local watchdog daemon in `core/watchdog_daemon.py` that polls Android storage/download roots and the workspace inbox, then routes incoming files into project-specific archives with memory synchronization.
- Kept the project documentation aligned with the current local Termux agent behavior.

### Changed
- Updated `core/agent.py` to split composite inputs into ordered sub-tasks and continue through the ReAct loop while preventing repeated identical validation and missing-file cycles.
- Updated `core/agent.py` to use precise write_file repair actions as the default response to syntax/test failure states.
- Updated `core/tools.py` to validate and normalize paths relative to the workspace root without allowing escapes or command injection patterns.
- Updated the project README and changelog to describe the deterministic repair model, sandbox safeguards, and local-only runtime design.

### Fixed
- Fixed infinite validation loops by detecting repeated failing validation parameters and switching to a minimal repair action.
- Fixed missing-file loop behavior by aborting read-back attempts that target non-existent workspace files instead of retrying the same operation.
- Fixed local path misuse by rejecting out-of-workspace access and blocking network tool routing for workspace-local tasks.
- Fixed clean failure behavior for missing pytest installations by returning a structured error result instead of a raw Python traceback.
- Preserved the exact quoted-string parsing behavior for `write_file` tasks so content extraction remains precise and compatibility-safe.

## [0.1.0] - 2026-11-06

### Added
- Initial local Termux agent architecture with core package, memory manager and root entrypoint.
- Initial safe tool abstraction for subprocess execution and file operations.
- Initial workspace JSON memory and direct task execution smoke tests.
