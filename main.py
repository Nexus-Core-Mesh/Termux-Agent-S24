#!/usr/bin/env python3
"""Main entrypoint for the lightweight local Termux agent."""

from __future__ import annotations

import argparse
import json

from core.agent import TermuxAgent


def _run_once(agent: TermuxAgent, task: str, cycles: int) -> dict:
    task_text = (task or "").strip()
    if not task_text:
        return {"status": "empty_task", "task": task_text, "history": []}
    plan = agent.plan_task(task_text)
    result = agent.run_autonomous(task_text, max_cycles=max(cycles, 1))
    result["plan"] = plan
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Termux agent.")
    parser.add_argument("--task", default="", help="High-level task for the agent")
    parser.add_argument("--cycles", type=int, default=5, help="Number of autonomous cycles to run")
    parser.add_argument("--status", action="store_true", help="Print the agent status instead of running a task")
    parser.add_argument("--memory", action="store_true", help="Print the memory snapshot instead of running a task")
    parser.add_argument("--history", action="store_true", help="Print recent history instead of running a task")
    parser.add_argument("--plans", action="store_true", help="Print recent plans instead of running a task")
    parser.add_argument("--reset-memory", action="store_true", help="Reset the workspace memory before running")
    args = parser.parse_args()

    agent = TermuxAgent(workspace_dir="workspace")

    if args.reset_memory:
        agent.memory.reset()

    if args.status:
        print(json.dumps(agent.status(), indent=2, ensure_ascii=False))
        return
    if args.memory:
        print(json.dumps(agent.memory_snapshot(), indent=2, ensure_ascii=False))
        return
    if args.history:
        print(json.dumps({"history": agent.memory.data.get("history", [])[-10:]}, indent=2, ensure_ascii=False))
        return
    if args.plans:
        print(json.dumps({"plans": agent.memory.data.get("plans", [])[-10:]}, indent=2, ensure_ascii=False))
        return

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

        result = _run_once(agent, user_input, 5)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
