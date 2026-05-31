"""
Stage 2 prompt rendering.

Takes preprocess.py JSONL records and the prompt template + guideline +
few-shot, substitutes placeholders, and writes one prompt per claim.

Usage:
  python -m research.eval_v3.stage2.render_prompt \
      --in research/eval_v3/stage2/outputs/C-1_deepseek_deepseek_preproc.jsonl \
      --out-dir research/eval_v3/stage2/outputs/prompts/C-1_deepseek_deepseek
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "propmt_template.md"
GUIDELINE_PATH = HERE / "action_validation_guideline.md"
FEWSHOT_PATH = HERE / "few_shot" / "stage2_examples.md"


def _format_evidence_block(evidence: dict) -> str:
    """Format routed evidence as labeled sections, JSON for structured data."""
    parts = []
    for channel, payload in evidence.items():
        parts.append(f"### {channel}")
        if isinstance(payload, str):
            parts.append(payload)
        else:
            parts.append("```json")
            parts.append(json.dumps(payload, ensure_ascii=False, indent=2))
            parts.append("```")
        parts.append("")
    return "\n".join(parts).rstrip()


def render_one(record: dict, template: str, guideline: str, fewshot: str) -> str:
    header = record["task_header"]
    claim = record["claim"]
    return (
        template
        .replace("{ACTION_VALIDATION_GUIDELINE}", guideline)
        .replace("{FEW_SHOT_EXAMPLES}", fewshot)
        .replace("{TASK_ID}", str(header.get("task_id") or ""))
        .replace("{TASK_INSTRUCTION}", str(header.get("task") or ""))
        .replace("{CURRENT_DATETIME}", str(header.get("current_datetime") or ""))
        .replace("{CLAIM_SPAN}", claim.get("span", ""))
        .replace("{CLAIM_TYPE}", claim.get("type", ""))
        .replace("{STEP_ID}", str(record.get("step_id", "")))
        .replace("{VALIDATION_SCOPE}", claim.get("validation_scope", ""))
        .replace("{ROUTED_EVIDENCE}", _format_evidence_block(record["evidence"]))
        .replace("{CLAIM_ID}", record.get("claim_id", ""))
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", type=Path, required=True,
                   help="Preprocess JSONL.")
    p.add_argument("--out-dir", type=Path, required=True,
                   help="Directory to write one .md file per claim.")
    p.add_argument("--template", type=Path, default=TEMPLATE_PATH)
    p.add_argument("--guideline", type=Path, default=GUIDELINE_PATH)
    p.add_argument("--fewshot", type=Path, default=FEWSHOT_PATH)
    p.add_argument("--limit", type=int, default=None,
                   help="Render only the first N claims (sanity check).")
    args = p.parse_args()

    template = args.template.read_text(encoding="utf-8")
    guideline = args.guideline.read_text(encoding="utf-8")
    fewshot = args.fewshot.read_text(encoding="utf-8")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    n = 0
    with args.in_path.open(encoding="utf-8") as f:
        for line in f:
            if args.limit is not None and n >= args.limit:
                break
            record = json.loads(line)
            prompt = render_one(record, template, guideline, fewshot)
            out_file = args.out_dir / f"{record['claim_id']}.md"
            out_file.write_text(prompt, encoding="utf-8")
            n += 1

    print(f"Rendered {n} prompts → {args.out_dir}")


if __name__ == "__main__":
    main()
