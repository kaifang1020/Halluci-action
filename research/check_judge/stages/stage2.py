"""Stage 2 placeholder. NOT runnable yet — keep as template only.

The LLM judge currently does not output ``gold_status`` / ``error_type`` /
``severity``. Once the stage-2 pipeline lands and emits these fields in the
LLM markdown, fill in ``METRICS`` below and run::

    python -m research.check_judge.run --stage stage2

Template (uncomment + adapt when stage 2 data exists):

    METRICS = [
        {
            "name": "gold_status",
            "kind": "classification",
            "field": "gold_status",
            "labels": ("verified", "action_gap", "unsupported",
                       "not_applicable", "needs_human_check"),
        },
        {
            "name": "error_type",
            "kind": "classification",
            "field": "error_type",
            # Labels are open-ended in the human guideline — list the ones
            # observed in annotations, plus a catch-all ``other``.
            "labels": ("none", "entity_link_gap", "missing_followup_action",
                       "failed_escalation_overclaim", "false_log_content",
                       "policy_overclaim", "other"),
        },
        {
            "name": "severity",
            "kind": "classification",
            "field": "severity",
            "labels": ("none", "low", "medium", "high"),
        },
    ]
"""

METRICS: list[dict] = []  # intentionally empty — see module docstring
