from __future__ import annotations

from pathlib import Path


STAGE1_DIR = Path(__file__).resolve().parent
REPO_ROOT = STAGE1_DIR.parents[2]
ENV_PATH = REPO_ROOT / ".env"

PROMPT_TEMPLATE_PATH = STAGE1_DIR / "prompt.md"
CLAIM_EXTRACTION_GUIDELINE_PATH = STAGE1_DIR / "claim_extraction_guideline.md"
STAGE1_EXAMPLES_PATH = STAGE1_DIR / "examples" / "stage1_examples.md"

OUTPUT_DIR = STAGE1_DIR / "outputs"
JSON_OUTPUT_DIR = OUTPUT_DIR / "json"
MD_OUTPUT_DIR = OUTPUT_DIR / "md"
PROMPT_OUTPUT_DIR = OUTPUT_DIR / "prompts"
RAW_OUTPUT_DIR = OUTPUT_DIR / "raw"
ERROR_OUTPUT_DIR = OUTPUT_DIR / "errors"

ALLOWED_TYPES = {
    "action_intention",
    "action_completion",
    "observation",
    "reasoning_conclusion",
    "constraint_or_policy",
    "recommendation",
    "non_actionable_text",
}

# Rule-based mapping from claim type to (requires_validation, validation_scope).
# Stage 1 does not call an LLM to decide these fields; they are derived from `type`.
# `validation_scope` is `False` (boolean) when no scope applies.
TYPE_VALIDATION_RULES: dict[str, tuple[bool, str | bool]] = {
    "action_intention": (True, "same_or_following_steps"),
    "action_completion": (True, "same_or_previous_steps"),
    "observation": (True, "previous_steps"),
    "constraint_or_policy": (True, "codebook.md"),
    "recommendation": (True, "same_or_previous_steps"),
    "reasoning_conclusion": (False, False),
    "non_actionable_text": (False, False),
}
