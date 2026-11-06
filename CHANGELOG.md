# Changelog

All notable updates for the Termux-Agent-S24 project.

## [Unreleased]

### Added
- Added robust decomposition of compound natural-language tasks using separators such as `and then`, `und dann` and `;`.
- Added multi-step ReAct execution so each sub-task is processed sequentially while preserving context from earlier results.
- Added workspace-safe path validation that blocks command chains and keeps file paths inside the repository workspace.
- Added a direct `--task` execution flow that triggers real autonomous behavior instead of idle output.
- Kept the project documentation aligned with the current local Termux agent behavior.

### Changed
- Updated `core/agent.py` to split composite inputs into ordered sub-tasks and continue through the ReAct loop until completion or the cycle limit is reached.
- Updated `core/tools.py` to validate and normalize paths relative to the workspace root without allowing escapes or command injection patterns.
- Updated the project README to describe robust task execution, compound parsing and multi-step agent behavior.

### Fixed
- Fixed misinterpretation of composite task strings such as `... and then ...` and `...; ...` as file paths or malformed commands.
- Fixed the idle-only execution path for direct text tasks passed through the CLI.

## [0.1.0] - 2026-11-06

### Added
- Initial local Termux agent architecture with core package, memory manager and root entrypoint.
- Initial safe tool abstraction for subprocess execution and file operations.
- Initial workspace JSON memory and direct task execution smoke tests.
