"""Parse human + LLM judge annotation markdown into structured claim dicts.

Both formats share the same skeleton:

    ## Step N
    ### Source
    ...source text...
    ### Atomic Claims
    #### {claim_id}        <- markdown header carries the id
    Claim: <text>
    Type: <type>
    Requires validation: <yes|no>
    ...optional fields...

Human files prepend a `## Annotation Summary` section that lists trajectory-level
verdicts. We skip everything before the first `## Step`.
"""

from __future__ import annotations

import re
from pathlib import Path


CLAIM_HEADER_RE = re.compile(r"^####\s+(\S+)\s*$")
STEP_HEADER_RE = re.compile(r"^##\s+Step\s+(\d+)\s*$", re.IGNORECASE)
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z _\-]*?):\s*(.*?)\s*$")
STEP_ID_FROM_CLAIM_RE = re.compile(r"S(\d+)", re.IGNORECASE)

# Map markdown field labels (lower-cased) to dict keys we keep.
FIELD_MAP = {
    "claim": "text",
    "type": "type",
    "requires validation": "requires_validation",
    "validation scope": "validation_scope",
    "gold status": "gold_status",
    "error type": "error_type",
    "severity": "severity",
}


def _normalize_yes_no(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in {"yes", "true"}:
        return "yes"
    if v in {"no", "false"}:
        return "no"
    return v or None


def _task_id_from_filename(path: Path) -> str:
    """`D-5_judge_stage1.md` -> `D-5`; `A-1.md` -> `A-1`."""
    stem = path.stem
    return stem.split("_")[0]


def parse_annotation_md(path: Path) -> dict:
    """Parse a single annotation markdown file.

    Returns
    -------
    {
        "task_id": str,
        "path": str,
        "claims": [
            {
                "claim_id": str,
                "step_id": int,
                "text": str | None,
                "type": str | None,
                "requires_validation": "yes"|"no"|None,
                "validation_scope": str | None,
                "gold_status": str | None,
                "error_type": str | None,
                "severity": str | None,
            },
            ...
        ],
    }
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    in_body = False
    current: dict | None = None
    claims: list[dict] = []

    for raw in lines:
        line = raw.rstrip()

        # Wait until the first `## Step N` to start parsing (skip Annotation Summary).
        if not in_body:
            if STEP_HEADER_RE.match(line):
                in_body = True
            else:
                continue

        header_match = CLAIM_HEADER_RE.match(line)
        if header_match:
            # Push the previous claim if any.
            if current is not None:
                claims.append(current)
            claim_id = header_match.group(1)
            step_match = STEP_ID_FROM_CLAIM_RE.search(claim_id)
            step_id = int(step_match.group(1)) if step_match else None
            current = {
                "claim_id": claim_id,
                "step_id": step_id,
                "text": None,
                "type": None,
                "requires_validation": None,
                "validation_scope": None,
                "gold_status": None,
                "error_type": None,
                "severity": None,
            }
            continue

        # A `## Step N` boundary or any other `##`/`###` resets the current block-collection
        # context — but the parser still continues; we just don't add fields to a claim that's
        # no longer "current". To avoid leaking later fields into the wrong claim, we close
        # the current claim when we hit a new `## Step` header (next claim header reopens).
        if STEP_HEADER_RE.match(line):
            if current is not None:
                claims.append(current)
                current = None
            continue

        if current is None:
            continue

        field_match = FIELD_RE.match(line)
        if not field_match:
            continue
        label = field_match.group(1).strip().lower()
        value = field_match.group(2).strip()
        key = FIELD_MAP.get(label)
        if key is None:
            continue
        if value == "":
            continue
        if key == "requires_validation":
            current[key] = _normalize_yes_no(value)
        else:
            current[key] = value

    # Flush trailing claim.
    if current is not None:
        claims.append(current)

    return {
        "task_id": _task_id_from_filename(path),
        "path": str(path),
        "claims": claims,
    }
