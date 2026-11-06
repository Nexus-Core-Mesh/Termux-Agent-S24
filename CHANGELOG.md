# Changelog

All notable updates for the Termux-Agent-S24 project.

## [Unreleased]

### Added
- Implemented a multi-step local ReAct loop with self-correction and history tracking.
- Extended the tool layer with safe local inspection, file checks and lightweight HTTP access.
- Added a polished project README and runtime documentation.
- Ensured task execution can happen directly from `--task` strings without idle-only fallback.

### Changed
- Improved the agent's task interpretation so natural-language instructions trigger concrete actions.
- Reinforced the workspace scoping logic to stay inside the local project directory.
- Kept the implementation lightweight and optimized for local Termux execution.

## [0.1.0] - 2026-11-06

### Added
- Initial local Termux agent architecture with core package, memory manager and root entrypoint.
- Initial safe tool abstraction for subprocess execution and file operations.
- Initial workspace JSON memory and direct task execution smoke tests.
