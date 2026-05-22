from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import click


def task_prefix(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", task_id)


def add_claim_ids(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(payload.get("task_id") or "T")
    prefix = task_prefix(task_id)
    for step in payload.get("steps") or []:
        step_id = step.get("step_id")
        for index, claim in enumerate(step.get("claims") or [], start=1):
            claim.setdefault("claim_id", f"{prefix}-S{step_id}-C{index}")
    return payload


def render(payload: dict[str, Any]) -> str:
    payload = add_claim_ids(payload)
    lines: list[str] = []
    for step in payload.get("steps") or []:
        step_id = step.get("step_id")
        lines.append(f"## Step {step_id}")
        lines.append("")
        lines.append("### Source")
        lines.append(str(step.get("source") or "").strip())
        lines.append("")
        lines.append("### Atomic Claims")
        lines.append("")
        claims = step.get("claims") or []
        if not claims:
            lines.append("- No extractable claims.")
            lines.append("")
            continue
        for claim in claims:
            lines.append(f"#### {claim.get('claim_id')}")
            lines.append(f"Claim: {claim.get('claim')}")
            lines.append("")
            lines.append(f"Type: {claim.get('type')}  ")
            req = "yes" if claim.get("requires_validation") else "no"
            lines.append(f"Requires validation: {req}  ")
            scope = claim.get("validation_scope") or "not_applicable"
            lines.append(f"Validation scope: {scope}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@click.command()
@click.argument("input_json", type=click.Path(exists=True, path_type=Path))
@click.argument("output_md", type=click.Path(path_type=Path))
def main(input_json: Path, output_md: Path) -> None:
    payload = json.loads(input_json.read_text(encoding="utf-8"))
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render(payload), encoding="utf-8")
    click.echo(f"Wrote {output_md}")


if __name__ == "__main__":
    main()

