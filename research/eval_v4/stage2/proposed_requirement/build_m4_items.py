#!/usr/bin/env python3
"""Build proposed-requirement claim items for one task across multiple author
models, reusing build_claim_items.build_items() with per-model stage1 root and
traj_key (so item_ids stay distinct across models).

Default: independent M-4 for deepseek_chat / gemini_flash / qwen
(the only authors that ran M-4). Output: outputs/m4_claim_items.jsonl
"""
from __future__ import annotations

import json
from pathlib import Path

import build_claim_items as bci

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[2]
STAGE1 = RESEARCH / "eval_v3-1_claim2action" / "stage1"
TRAJ_DIR = RESEARCH / "experiments_v2" / "real" / "independent" / "manufacturing" / "trajectories"

# model label -> (stage1 results dir, independent M-4 trajectory filename)
MODELS = {
    "deepseek_chat": ("results_deepseek_chat", "M-4_deepseek_deepseek_chat.json"),
    "gemini_flash": ("results_gemini_flash", "M-4_gemini_vertexai_hs3645_gemini_3_flash_preview.json"),
    "qwen": ("results_qwen", "M-4_qwen_qwen3_8b.json"),
}
TASK = "M-4"


def main() -> None:
    all_items: list[dict] = []
    for model, (stage1_dir, traj_name) in MODELS.items():
        traj = TRAJ_DIR / traj_name
        if not traj.exists():
            print(f"  [skip] {model}: trajectory not found {traj}")
            continue
        # repoint the reusable builder at this model's stage1 + give each model a
        # distinct traj_key so item_ids don't collide.
        bci.STAGE1_ROOT = STAGE1 / stage1_dir
        bci.traj_key_for = (lambda m: (lambda task_id, meta:
            (f"{meta['chain']}__{task_id}_{m}" if meta["condition"] == "dependent"
             else f"{task_id}_{m}")))(model)
        items, skipped = bci.build_items([traj])
        for it in items:
            it["author_model"] = model
        all_items.extend(items)
        print(f"  {model}: {len(items)} action-claim items "
              f"({'; '.join(s['reason'] for s in skipped) or 'no skips'})")

    out = HERE / "outputs" / "m4_claim_items.jsonl"
    out.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in all_items) + "\n",
                   encoding="utf-8")
    print(f"\nTotal {len(all_items)} items -> {out}")


if __name__ == "__main__":
    main()
