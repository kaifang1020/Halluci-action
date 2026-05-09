from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from config import ALLOWED_TYPES


def validate(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload.get("task_id"), str) or not payload.get("task_id"):
        errors.append("missing or invalid task_id")
    if not isinstance(payload.get("trajectory_file"), str):
        errors.append("missing or invalid trajectory_file")
    steps = payload.get("steps")
    if not isinstance(steps, list):
        errors.append("steps must be a list")
        return errors
    for step_index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"steps[{step_index}] must be an object")
            continue
        if not isinstance(step.get("step_id"), int):
            errors.append(f"steps[{step_index}].step_id must be an int")
        if not isinstance(step.get("source"), str):
            errors.append(f"steps[{step_index}].source must be a string")
        claims = step.get("claims")
        if not isinstance(claims, list):
            errors.append(f"steps[{step_index}].claims must be a list")
            continue
        for claim_index, claim in enumerate(claims):
            loc = f"steps[{step_index}].claims[{claim_index}]"
            if not isinstance(claim, dict):
                errors.append(f"{loc} must be an object")
                continue
            if not isinstance(claim.get("claim"), str) or not claim.get("claim", "").strip():
                errors.append(f"{loc}.claim must be a non-empty string")
            if claim.get("type") not in ALLOWED_TYPES:
                errors.append(f"{loc}.type must be one of {sorted(ALLOWED_TYPES)}")
            if not isinstance(claim.get("requires_validation"), bool):
                errors.append(f"{loc}.requires_validation must be boolean")
    return errors


@click.command()
@click.argument("input_json", type=click.Path(exists=True, path_type=Path))
def main(input_json: Path) -> None:
    payload = json.loads(input_json.read_text(encoding="utf-8"))
    errors = validate(payload)
    if errors:
        for error in errors:
            click.echo(f"[error] {error}", err=True)
        raise SystemExit(1)
    click.echo(f"OK: {input_json}")


if __name__ == "__main__":
    main()

