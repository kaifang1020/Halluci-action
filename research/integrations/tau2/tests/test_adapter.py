from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from research.integrations.tau2.adapter import adapt_tau2_run, select_tau2_run
from research.integrations.tau2.contract import CanonicalTrajectory


HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "minimal_tau2_result.json"


class Tau2AdapterTest(unittest.TestCase):
    def load_fixture(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_adapts_agent_projection_and_preserves_source_events(self) -> None:
        payload = self.load_fixture()
        simulation, task = select_tau2_run(payload, task_id="demo-1", trial=0)

        trajectory = adapt_tau2_run(payload, simulation, task)

        self.assertIsInstance(trajectory, CanonicalTrajectory)
        self.assertEqual(trajectory.task, "Please check account ACC-7 and enable notifications.")
        self.assertEqual(trajectory.interaction_metrics.assistant_turns, 4)
        self.assertEqual(trajectory.interaction_metrics.user_turns, 2)
        self.assertEqual(trajectory.interaction_metrics.assistant_tool_calls, 2)
        self.assertEqual(trajectory.interaction_metrics.user_tool_calls, 1)
        self.assertTrue(trajectory.interaction_metrics.is_multi_turn)

        projected_calls = [
            call for step in trajectory.steps for call in step.tool_calls
        ]
        self.assertEqual(
            [call.tool_name for call in projected_calls],
            ["get_account", "update_notifications"],
        )
        self.assertNotIn(
            "record_confirmation", {call.tool_name for call in projected_calls}
        )
        self.assertIn(
            "record_confirmation",
            {
                call.tool_name
                for event in trajectory.events
                for call in event.tool_calls
            },
        )

        update_step = trajectory.steps[2]
        self.assertEqual(update_step.source_turn_idx, 6)
        self.assertEqual(update_step.tool_results[0].status, "success")
        self.assertEqual(update_step.tool_results[0].result["enabled"], True)
        self.assertEqual(trajectory.adapter_warnings, [])

    def test_reference_actions_are_non_binding_without_action_reward(self) -> None:
        payload = self.load_fixture()
        simulation, task = select_tau2_run(payload)
        trajectory = adapt_tau2_run(payload, simulation, task)

        self.assertEqual(
            trajectory.evaluator_context.reference_solution.binding,
            "reference_only",
        )

        action_payload = deepcopy(payload)
        action_payload["tasks"][0]["evaluation_criteria"]["reward_basis"].append(
            "ACTION"
        )
        simulation, task = select_tau2_run(action_payload)
        trajectory = adapt_tau2_run(action_payload, simulation, task)
        self.assertEqual(
            trajectory.evaluator_context.reference_solution.binding,
            "required",
        )

    def test_serialized_steps_keep_legacy_pipeline_keys(self) -> None:
        payload = self.load_fixture()
        simulation, task = select_tau2_run(payload)
        serialized = adapt_tau2_run(payload, simulation, task).model_dump()

        step = serialized["steps"][1]
        self.assertIn("assistant_text", step)
        self.assertIn("tool_calls", step)
        self.assertIn("tool_results", step)
        self.assertEqual(step["tool_calls"][0]["call_id"], "agent-call-1")
        self.assertEqual(step["tool_calls"][0]["tool_name"], "get_account")
        self.assertEqual(step["tool_calls"][0]["parameters"]["account_id"], "ACC-7")


if __name__ == "__main__":
    unittest.main()

