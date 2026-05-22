from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import click

from config import (
    CLAIM_EXTRACTION_GUIDELINE_PATH,
    ENV_PATH,
    ERROR_OUTPUT_DIR,
    JSON_OUTPUT_DIR,
    MD_OUTPUT_DIR,
    PROMPT_OUTPUT_DIR,
    PROMPT_TEMPLATE_PATH,
    RAW_OUTPUT_DIR,
    STAGE1_EXAMPLES_PATH,
    TYPE_VALIDATION_MAP,
)
from render_md import add_claim_ids, render
from validate_output import validate


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def apply_type_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    for step in payload.get("steps") or []:
        for claim in step.get("claims") or []:
            mapping = TYPE_VALIDATION_MAP.get(claim.get("type") or "", {})
            claim["requires_validation"] = mapping.get("requires_validation", False)
            claim["validation_scope"] = mapping.get("validation_scope", "not_applicable")
    return payload


def parse_json_from_llm(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def task_id_from_path(path: Path) -> str:
    # Expected .../<domain>/<TASK_ID>/<file>.json
    parent = path.parent.name
    return parent if parent else path.stem


def extract_assistant_text_view(trajectory_path: Path) -> dict[str, Any]:
    payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
    steps_out: list[dict[str, Any]] = []

    raw_steps = payload.get("steps") or payload.get("trajectory") or []
    if isinstance(raw_steps, dict):
        raw_steps = raw_steps.get("steps") or []

    for index, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            continue
        step_id = step.get("step_id") or step.get("index") or index
        assistant_text = step.get("assistant_text") or step.get("assistant") or ""
        steps_out.append(
            {
                "step_id": int(step_id),
                "assistant_text": str(assistant_text or ""),
            }
        )

    task_id = str(payload.get("task_id") or task_id_from_path(trajectory_path))
    return {
        "task_id": task_id,
        "trajectory_file": str(trajectory_path),
        "user_instruction": payload.get("task") or payload.get("user_instruction") or "",
        "steps": steps_out,
    }


def build_prompt(trajectory_path: Path) -> str:
    template = read_text(PROMPT_TEMPLATE_PATH)
    view = extract_assistant_text_view(trajectory_path)
    target_view = json.dumps(view, indent=2, ensure_ascii=False)
    return (
        template.replace("{{CLAIM_EXTRACTION_GUIDELINE}}", read_text(CLAIM_EXTRACTION_GUIDELINE_PATH))
        .replace("{{STAGE1_EXAMPLES}}", read_text(STAGE1_EXAMPLES_PATH))
        .replace("{{TARGET_ASSISTANT_TEXT_VIEW}}", target_view)
    )


def call_openai_compatible(prompt: str, model: str, base_url: str | None, api_key: str | None) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"), base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "You are a precise Stage 1 claim extraction annotator. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content or ""


def default_output_stem(trajectory_path: Path) -> str:
    try:
        payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return task_id_from_path(trajectory_path)

    task_id = payload.get("task_id")
    if task_id:
        return str(task_id)
    return task_id_from_path(trajectory_path)


def output_paths(stem: str) -> dict[str, Path]:
    return {
        "prompt": PROMPT_OUTPUT_DIR / f"{stem}.md",
        "raw": RAW_OUTPUT_DIR / f"{stem}.txt",
        "json": JSON_OUTPUT_DIR / f"{stem}.json",
        "md": MD_OUTPUT_DIR / f"{stem}.md",
        "error": ERROR_OUTPUT_DIR / f"{stem}.txt",
    }


def should_skip(stem: str, dry_run: bool, overwrite: bool) -> bool:
    if overwrite:
        return False
    paths = output_paths(stem)
    required = [paths["prompt"]] if dry_run else [paths["prompt"], paths["raw"], paths["json"], paths["md"]]
    return all(path.exists() for path in required)


def run_one(
    trajectory_path: Path,
    stem: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    dry_run: bool,
    overwrite: bool,
) -> None:
    if should_skip(stem, dry_run=dry_run, overwrite=overwrite):
        click.echo(f"Skip existing output: {stem}")
        return

    prompt = build_prompt(trajectory_path)
    paths = output_paths(stem)

    PROMPT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths["prompt"].write_text(prompt, encoding="utf-8")
    click.echo(f"Wrote prompt: {paths['prompt']}")

    if dry_run:
        return

    if not model:
        raise click.ClickException("Missing --model or STAGE1_MODEL.")

    raw = call_openai_compatible(prompt, model=model, base_url=base_url, api_key=api_key)
    RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths["raw"].write_text(raw, encoding="utf-8")
    click.echo(f"Wrote raw model output: {paths['raw']}")

    payload = parse_json_from_llm(raw)
    errors = validate(payload)
    if errors:
        raise click.ClickException("Invalid Stage 1 output:\n" + "\n".join(errors))

    payload = apply_type_mapping(payload)
    payload = add_claim_ids(payload)
    JSON_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    click.echo(f"Wrote JSON: {paths['json']}")

    MD_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths["md"].write_text(render(payload), encoding="utf-8")
    click.echo(f"Wrote Markdown: {paths['md']}")


def load_target_set(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise click.ClickException("target-set must be a JSON list.")
    targets: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise click.ClickException(f"target-set item {index} must be an object.")
        raw_path = item.get("raw_path") or item.get("trajectory") or item.get("trajectory_path")
        if not raw_path:
            raise click.ClickException(f"target-set item {index} is missing raw_path.")
        targets.append(item)
    return targets


def target_path_and_stem(item: dict[str, Any]) -> tuple[Path, str]:
    trajectory_path = Path(str(item.get("raw_path") or item.get("trajectory") or item.get("trajectory_path")))
    stem = str(item.get("output_stem") or item.get("task_id") or default_output_stem(trajectory_path))
    return trajectory_path, stem


@click.command()
@click.option("--trajectory", "trajectory_path", type=click.Path(exists=True, path_type=Path))
@click.option("--target-set", type=click.Path(exists=True, path_type=Path), help="JSON list of trajectories to process.")
@click.option("--model", default=os.environ.get("STAGE1_MODEL", ""), help="OpenAI-compatible model name.")
@click.option("--base-url", default=os.environ.get("STAGE1_BASE_URL", None), help="OpenAI-compatible base URL.")
@click.option("--api-key", default=os.environ.get("STAGE1_API_KEY", None), help="API key. Defaults to environment.")
@click.option("--dry-run", is_flag=True, help="Only build and save the prompt; do not call the model.")
@click.option("--output-stem", default=None, help="Output filename stem. Defaults to task ID.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing outputs.")
@click.option("--limit", type=int, default=None, help="Only process the first N targets in --target-set.")
@click.option("--continue-on-error", is_flag=True, help="Continue batch processing after an item fails.")
def main(
    trajectory_path: Path | None,
    target_set: Path | None,
    model: str,
    base_url: str | None,
    api_key: str | None,
    dry_run: bool,
    output_stem: str | None,
    overwrite: bool,
    limit: int | None,
    continue_on_error: bool,
) -> None:
    load_dotenv()
    if not model:
        model = os.environ.get("STAGE1_MODEL", "")
    if base_url is None:
        base_url = os.environ.get("STAGE1_BASE_URL")
    if api_key is None:
        api_key = os.environ.get("STAGE1_API_KEY")

    if bool(trajectory_path) == bool(target_set):
        raise click.ClickException("Provide exactly one of --trajectory or --target-set.")
    if output_stem and target_set:
        raise click.ClickException("--output-stem is only supported with --trajectory.")

    if trajectory_path:
        stem = output_stem or default_output_stem(trajectory_path)
        run_one(
            trajectory_path=trajectory_path,
            stem=stem,
            model=model,
            base_url=base_url,
            api_key=api_key,
            dry_run=dry_run,
            overwrite=overwrite,
        )
        return

    assert target_set is not None
    targets = load_target_set(target_set)
    if limit is not None:
        targets = targets[:limit]

    failures = 0
    for index, item in enumerate(targets, start=1):
        item_path, stem = target_path_and_stem(item)
        click.echo(f"\n[{index}/{len(targets)}] {stem}: {item_path}")
        try:
            run_one(
                trajectory_path=item_path,
                stem=stem,
                model=model,
                base_url=base_url,
                api_key=api_key,
                dry_run=dry_run,
                overwrite=overwrite,
            )
        except Exception as exc:
            failures += 1
            ERROR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            error_path = ERROR_OUTPUT_DIR / f"{stem}.txt"
            error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            click.echo(f"[error] {stem}: {exc}", err=True)
            click.echo(f"Wrote error: {error_path}", err=True)
            if not continue_on_error:
                raise

    if failures:
        raise click.ClickException(f"Completed with {failures} failure(s).")


if __name__ == "__main__":
    main()
