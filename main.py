#!/usr/bin/env python3
"""Main entrypoint for the lightweight local Termux agent."""

from __future__ import annotations

import argparse
import json

from core.agent import TermuxAgent


def _run_once(agent: TermuxAgent, task: str, cycles: int) -> dict:
    return agent.run_once(task=task) if task else agent.run_autonomous(task, max_cycles=cycles)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Termux agent.")
    parser.add_argument("--task", default="", help="High-level task for the agent")
    parser.add_argument("--cycles", type=int, default=3, help="Number of autonomous cycles to run")
    args = parser.parse_args()

    agent = TermuxAgent(workspace_dir="workspace")

    if args.task:
        result = _run_once(agent, args.task, args.cycles)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    print("Termux Agent S24 ready. Enter goals or 'exit' to quit.")
    while True:
        try:
            user_input = input("Goal> ").strip()
        except EOFError:
            print()
            break

        if not user_input or user_input.lower() in {"exit", "quit", "bye"}:
            if not user_input:
                continue
            print("Agent session ended.")
            break

        result = _run_once(agent, user_input, max_cycles=3)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
