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

# Deterministic mapping: claim type → requires_validation + validation_scope.
# Applied by extract.py after parsing LLM output so the LLM only needs to
# decide the claim type.
TYPE_VALIDATION_MAP: dict[str, dict] = {
    "action_intention":     {"requires_validation": True,  "validation_scope": "same_or_following_steps"},
    "action_completion":    {"requires_validation": True,  "validation_scope": "same_or_previous_steps"},
    "observation":          {"requires_validation": True,  "validation_scope": "previous_steps"},
    "constraint_or_policy": {"requires_validation": True,  "validation_scope": "codebook.md"},
    "reasoning_conclusion": {"requires_validation": False, "validation_scope": "not_applicable"},
    "recommendation":       {"requires_validation": True,  "validation_scope": "same_or_previous_steps"},
    "non_actionable_text":  {"requires_validation": False, "validation_scope": "not_applicable"},
}
