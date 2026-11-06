#!/usr/bin/env python3
"""Main entrypoint for the lightweight local Termux agent."""

from __future__ import annotations

import argparse

from core.agent import TermuxAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Termux agent.")
    parser.add_argument("--task", default="Initialize local autonomous Termux agent", help="High-level task for the agent")
    parser.add_argument("--command", default=None, help="Optional command to execute in the local workspace")
    parser.add_argument("--cycles", type=int, default=1, help="Number of loop iterations to run")
    args = parser.parse_args()

    agent = TermuxAgent(workspace_dir="workspace")
    result = agent.run_loop(task=args.task, command=args.command, max_cycles=args.cycles)
    print(result)


if __name__ == "__main__":
    main()
