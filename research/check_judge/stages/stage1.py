"""Stage 1 metric configuration: claim extraction + claim_type + requires_validation.

To add more metrics later (e.g. stage 2 ``gold_status``), copy this file as
``stage2.py``, append entries to ``METRICS``, and run with ``--stage stage2``.
``run.py`` consumes ``METRICS`` declaratively, no need to touch it.
"""

from __future__ import annotations


# Keep in sync with research/eval_v2/stage1/config.py::ALLOWED_TYPES
ALLOWED_TYPES = (
    "action_intention",
    "action_completion",
    "observation",
    "reasoning_conclusion",
    "constraint_or_policy",
    "recommendation",
    "non_actionable_text",
)


METRICS = [
    # 1) Atomic claim coverage (P/R/F1 over aligned claim sets).
    {
        "name": "claim_extraction",
        "kind": "set",
    },
    # 2) Claim type classification agreement, computed over aligned pairs.
    {
        "name": "claim_type",
        "kind": "classification",
        "field": "type",
        "labels": ALLOWED_TYPES,
    },
    # 3) requires_validation flag agreement.
    {
        "name": "requires_validation",
        "kind": "classification",
        "field": "requires_validation",
        "labels": ("yes", "no"),
    },
]
