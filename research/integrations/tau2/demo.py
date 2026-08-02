"""CLI demo for adapting one Tau2 simulation into the canonical contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapter import adapt_tau2_run, select_tau2_run
from .contract import CanonicalTrajectory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--trial", type=int)
    parser.add_argument("--simulation-index", type=int, default=0)
    parser.add_argument(
        "--tool-definitions",
        type=Path,
        help="Optional JSON list exported from Tau2 Environment.get_info(include_tool_info=True).",
    )
    parser.add_argument("--schema-out", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.results.read_text(encoding="utf-8"))
    simulation, task = select_tau2_run(
        payload,
        task_id=args.task_id,
        trial=args.trial,
        simulation_index=args.simulation_index,
    )
    tool_definitions = None
    if args.tool_definitions is not None:
        tool_definitions = json.loads(
            args.tool_definitions.read_text(encoding="utf-8")
        )
        if not isinstance(tool_definitions, list):
            parser.error("--tool-definitions must contain a JSON list")
    trajectory = adapt_tau2_run(
        payload,
        simulation,
        task,
        tool_definitions=tool_definitions,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        trajectory.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    if args.schema_out is not None:
        args.schema_out.parent.mkdir(parents=True, exist_ok=True)
        args.schema_out.write_text(
            json.dumps(CanonicalTrajectory.model_json_schema(), indent=2),
            encoding="utf-8",
        )

    metrics = trajectory.interaction_metrics
    print(f"trajectory: {trajectory.trajectory_id}")
    print(f"task: {trajectory.task_id}")
    print(f"assistant turns: {metrics.assistant_turns}")
    print(f"user turns: {metrics.user_turns}")
    print(f"assistant actions: {metrics.assistant_tool_calls}")
    print(f"user actions excluded from A_tau: {metrics.user_tool_calls}")
    print(
        "reference action binding: "
        f"{trajectory.evaluator_context.reference_solution.binding}"
    )
    print(f"warnings: {len(trajectory.adapter_warnings)}")
    print(f"wrote: {args.out}")


if __name__ == "__main__":
    main()
