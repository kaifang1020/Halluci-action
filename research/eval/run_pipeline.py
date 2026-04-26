"""
Run the Halluci-Action evaluation pipeline end to end.

Default behavior:
  - run pass1, pass2, pass3_stage1, pass3_stage2
  - write one compact final JSON to evaluations/results/
  - store intermediate files in a temporary directory and delete them

Use --keep-intermediate to keep pass outputs for debugging.
Use --pass1-existing to skip the expensive Pass 1 LLM extraction when you
already have a Pass 1 JSON file.
Use --heuristic to preview Pass 3 without LLM calls.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import click

from llm_config import apply_profile, load_env_file, resolve_api_key, resolve_base_url, resolve_model


HERE = Path(__file__).resolve().parent


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def default_pass1_script() -> Path:
    local = HERE / "pass1.py"
    if local.exists():
        return local
    downloads = Path.home() / "Downloads" / "pass1.py"
    if downloads.exists():
        return downloads
    return local


def run_command(cmd: list[str], label: str) -> None:
    click.echo(f"\n[{label}] {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=HERE)


def compact_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id"),
        "step_id": action.get("step_id"),
        "tool_name": action.get("tool_name"),
        "parameters_summary": action.get("parameters_summary"),
        "status": action.get("status"),
        "result_summary": action.get("result_summary"),
    }


def claim_text(claim: dict[str, Any]) -> str:
    return str(claim.get("text") or claim.get("claim_text") or "")


def build_compact_final(
    trajectory_path: Path,
    pass1_path: Path,
    pass2_path: Path,
    stage1_path: Path,
    stage2_path: Path,
    gaps_only: bool = False,
) -> dict[str, Any]:
    trajectory = load_json(trajectory_path)
    claims = load_json(pass1_path)
    actions = load_json(pass2_path)
    stage1_results = load_json(stage1_path)
    stage2_results = load_json(stage2_path)

    actions_by_id = {
        action["action_id"]: action
        for action in actions
        if isinstance(action.get("action_id"), int)
    }
    stage1_by_claim = {
        item["claim_id"]: item
        for item in stage1_results
        if isinstance(item.get("claim_id"), int)
    }
    stage2_by_claim = {
        item["claim_id"]: item
        for item in stage2_results
        if isinstance(item.get("claim_id"), int)
    }

    final_claims: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = claim.get("claim_id")
        stage1 = stage1_by_claim.get(claim_id, {})
        stage2 = stage2_by_claim.get(claim_id)

        if stage2:
            verification_stage = "stage2"
            final_status = stage2.get("final_status")
            gap_type = stage2.get("gap_type")
            ha_type = stage2.get("ha_type")
            matched_ids = stage2.get("matched_action_ids") or []
            evidence_summary = stage2.get("evidence_summary", "")
            reason = stage2.get("reason", "")
            confidence = stage2.get("confidence", "low")
            cross_step_status = stage2.get("cross_step_status")
            local_status = stage2.get("stage1_local_status")
        else:
            verification_stage = "stage1"
            local_status = stage1.get("local_status")
            cross_step_status = None
            final_status = "verified" if local_status == "verified" else "gap"
            gap_type = stage1.get("gap_type")
            ha_type = stage1.get("ha_type")
            matched_ids = stage1.get("matched_action_ids") or []
            evidence_summary = ""
            reason = stage1.get("reason", "")
            confidence = stage1.get("confidence", "low")

        if gaps_only and final_status != "gap":
            continue

        final_claims.append(
            {
                "claim_id": claim_id,
                "step_id": claim.get("step_id"),
                "claim_text": claim_text(claim),
                "claim_type": claim.get("claim_type"),
                "temporal": claim.get("temporal"),
                "verification_stage": verification_stage,
                "local_status": local_status,
                "cross_step_status": cross_step_status,
                "final_status": final_status,
                "gap_type": gap_type,
                "ha_type": ha_type,
                "matched_action_ids": matched_ids,
                "matched_actions": [
                    compact_action(actions_by_id[action_id])
                    for action_id in matched_ids
                    if action_id in actions_by_id
                ],
                "evidence_summary": evidence_summary,
                "reason": reason,
                "confidence": confidence,
            }
        )

    gap_claims = [claim for claim in final_claims if claim.get("final_status") == "gap"]
    ha_counts: dict[str, int] = {}
    gap_counts: dict[str, int] = {}
    for claim in gap_claims:
        ha_type = claim.get("ha_type") or "None"
        gap_type = claim.get("gap_type") or "None"
        ha_counts[ha_type] = ha_counts.get(ha_type, 0) + 1
        gap_counts[gap_type] = gap_counts.get(gap_type, 0) + 1

    return {
        "trajectory_id": trajectory.get("trajectory_id"),
        "trajectory_file": str(trajectory_path),
        "task": trajectory.get("task"),
        "summary": {
            "claims_total": len(claims),
            "actions_total": len(actions),
            "claims_in_output": len(final_claims),
            "gaps_total": len(gap_claims),
            "ha_type_counts": ha_counts,
            "gap_type_counts": gap_counts,
        },
        "claims": final_claims,
    }


@click.command()
@click.option("--trajectory", "trajectory_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Trajectory JSON file to evaluate.")
@click.option("--output-dir", type=click.Path(path_type=Path),
              help="Directory for compact final results. Defaults to <trajectory_dir>/evaluations/results.")
@click.option("--work-dir", type=click.Path(path_type=Path),
              help="Directory for intermediate files when --keep-intermediate is set.")
@click.option("--keep-intermediate", is_flag=True, default=False,
              help="Keep pass1/pass2/stage1/stage2 outputs for debugging.")
@click.option("--pass1-script", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to pass1.py. Defaults to repo pass1.py or ~/Downloads/pass1.py.")
@click.option("--pass1-existing", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Existing Pass 1 JSON. Skips running pass1.py.")
@click.option("--registry-path", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Explicit registry.py path for pass1.")
@click.option("--api-key", default=None, envvar="OPENAI_API_KEY",
              help="OpenAI API key. Falls back to OPENAI_API_KEY.")
@click.option("--base-url", default=None,
              help="OpenAI-compatible base URL. Falls back to env config.")
@click.option("--env-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Load API/model configuration from an env file.")
@click.option("--profile", default=None,
              help="LLM profile to use from the env file, e.g. openai, deepseek, gemini.")
@click.option("--model-1a", default=None, help="Defaults to env config or gpt-4o.")
@click.option("--model-1b", default=None, help="Defaults to env config or gpt-4o.")
@click.option("--model-stage1", default=None, help="Defaults to env config or gpt-4o.")
@click.option("--model-stage2", default=None, help="Defaults to env config or gpt-4o.")
@click.option("--heuristic", is_flag=True, default=False,
              help="Use heuristic mode for pass3_stage1/pass3_stage2.")
@click.option("--max-actions", default=8, show_default=True,
              help="Max candidate actions for pass3_stage2.")
@click.option("--gaps-only", is_flag=True, default=False,
              help="Only include final gap claims in compact final output.")
def main(
    trajectory_path: Path,
    output_dir: Path | None,
    work_dir: Path | None,
    keep_intermediate: bool,
    pass1_script: Path | None,
    pass1_existing: Path | None,
    registry_path: Path | None,
    api_key: str | None,
    base_url: str | None,
    env_file: Path | None,
    profile: str | None,
    model_1a: str | None,
    model_1b: str | None,
    model_stage1: str | None,
    model_stage2: str | None,
    heuristic: bool,
    max_actions: int,
    gaps_only: bool,
) -> None:
    """Run Pass 1, Pass 2, Pass 3 Stage 1, Pass 3 Stage 2, then write compact final JSON."""
    load_env_file(env_file)
    apply_profile(profile)
    api_key = resolve_api_key(api_key) or None
    base_url = resolve_base_url(base_url)
    model_1a = resolve_model("PASS1A", model_1a)
    model_1b = resolve_model("PASS1B", model_1b)
    model_stage1 = resolve_model("STAGE1", model_stage1)
    model_stage2 = resolve_model("STAGE2", model_stage2)

    trajectory_path = trajectory_path.resolve()
    output_dir = output_dir or trajectory_path.parent / "evaluations" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_context: tempfile.TemporaryDirectory[str] | None = None
    if keep_intermediate:
        work_root = work_dir or trajectory_path.parent / "evaluations" / "debug" / trajectory_path.stem
        work_root.mkdir(parents=True, exist_ok=True)
    else:
        temp_context = tempfile.TemporaryDirectory(prefix=f"{trajectory_path.stem}__", dir="/tmp")
        work_root = Path(temp_context.name)

    try:
        pass1_path = work_root / f"{trajectory_path.stem}__pass1.json"
        pass2_path = work_root / f"{trajectory_path.stem}__pass2.json"
        stage1_path = work_root / f"{trajectory_path.stem}__pass3_stage1.json"
        stage2_path = work_root / f"{trajectory_path.stem}__pass3_stage2.json"

        if pass1_existing:
            shutil.copy2(pass1_existing, pass1_path)
            click.echo(f"[Pass 1] Reusing existing file → {pass1_path}")
        else:
            script = (pass1_script or default_pass1_script()).resolve()
            if not script.exists():
                raise click.ClickException(f"pass1.py not found: {script}")
            cmd = [
                sys.executable,
                str(script),
                "run",
                "--trajectory",
                str(trajectory_path),
                "--output-dir",
                str(work_root),
                "--model-1a",
                model_1a,
                "--model-1b",
                model_1b,
            ]
            if registry_path:
                cmd.extend(["--registry-path", str(registry_path.resolve())])
            if api_key:
                cmd.extend(["--api-key", api_key])
            if base_url:
                cmd.extend(["--base-url", base_url])
            run_command(cmd, "Pass 1")

        run_command(
            [
                sys.executable,
                str(HERE / "pass2.py"),
                "run",
                "--trajectory",
                str(trajectory_path),
                "--output",
                str(pass2_path),
            ],
            "Pass 2",
        )

        stage1_cmd = [
            sys.executable,
            str(HERE / "pass3_stage1.py"),
            "run",
            "--pass1",
            str(pass1_path),
            "--pass2",
            str(pass2_path),
            "--output",
            str(stage1_path),
            "--model",
            model_stage1,
        ]
        if heuristic:
            stage1_cmd.append("--heuristic")
        elif api_key:
            stage1_cmd.extend(["--api-key", api_key])
        if base_url:
            stage1_cmd.extend(["--base-url", base_url])
        run_command(stage1_cmd, "Pass 3 Stage 1")

        stage2_cmd = [
            sys.executable,
            str(HERE / "pass3_stage2.py"),
            "run",
            "--pass1",
            str(pass1_path),
            "--pass2",
            str(pass2_path),
            "--stage1",
            str(stage1_path),
            "--output",
            str(stage2_path),
            "--model",
            model_stage2,
            "--max-actions",
            str(max_actions),
        ]
        if heuristic:
            stage2_cmd.append("--heuristic")
        elif api_key:
            stage2_cmd.extend(["--api-key", api_key])
        if base_url:
            stage2_cmd.extend(["--base-url", base_url])
        run_command(stage2_cmd, "Pass 3 Stage 2")

        final = build_compact_final(
            trajectory_path=trajectory_path,
            pass1_path=pass1_path,
            pass2_path=pass2_path,
            stage1_path=stage1_path,
            stage2_path=stage2_path,
            gaps_only=gaps_only,
        )
        final_path = output_dir / f"{trajectory_path.stem}__final.json"
        save_json(final, final_path)

        click.echo(f"\n[Final] Saved compact result → {final_path}")
        click.echo(json.dumps(final["summary"], indent=2, ensure_ascii=False))
        if keep_intermediate:
            click.echo(f"[Debug] Intermediate files kept in → {work_root}")
    finally:
        if temp_context is not None:
            temp_context.cleanup()


if __name__ == "__main__":
    main()
