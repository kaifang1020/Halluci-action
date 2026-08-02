#!/usr/bin/env python3
"""Build proposed-requirement claim items for ALL tasks across all five v2 author
models, independent + dependent, reusing build_claim_items.build_items().

Per-model experiments root / trajectory suffix / stage1 dir differ, so we
monkeypatch the reusable builder per model (same trick as build_task_items.py).

Output: outputs/all_claim_items.jsonl  (every action_intention/action_completion
claim with requires_validation across the 5 models).
"""
from __future__ import annotations

import json
from pathlib import Path

import build_claim_items as bci

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[2]
STAGE1 = RESEARCH / "eval_v3-1_claim2action" / "stage1"

# model -> (experiments root, trajectory filename suffix, stage1 results dir)
MODELS = {
    "deepseek_chat":     ("experiments_v2/real", "_deepseek_deepseek_chat", "results_deepseek_chat"),
    "deepseek_reasoner": ("experiments_v2",      "_deepseek_deepseek_reasoner", "results_deepseek_reasoner"),
    "gemini_flash":      ("experiments_v2/real", "_gemini_vertexai_hs3645_gemini_3_flash_preview", "results_gemini_flash"),
    "gpt4o_mini":        ("experiments_v1",      "_openai_gpt_4o_mini", "results_gpt4o_mini"),
    "qwen":              ("experiments_v2/real", "_qwen_qwen3_8b", "results_qwen"),
}


def _generic_metadata(traj_path: Path) -> dict[str, str]:
    parts = traj_path.parts
    for i, p in enumerate(parts):
        if p in ("independent", "dependent"):
            cond = p
            domain = parts[i + 1] if i + 1 < len(parts) else "unknown"
            chain = parts[i + 2] if cond == "dependent" and i + 2 < len(parts) else "single"
            return {"condition": cond, "domain": domain, "chain": chain}
    return {"condition": "independent", "domain": "unknown", "chain": "single"}


def main() -> None:
    bci.infer_real_metadata = _generic_metadata
    all_items: list[dict] = []
    for model, (root, suffix, stage1_dir) in MODELS.items():
        base = RESEARCH / root
        trajs = sorted(base.glob(f"independent/*/trajectories/*{suffix}.json")) \
              + sorted(base.glob(f"dependent/*/*/trajectories/*{suffix}.json"))
        if not trajs:
            print(f"  {model}: NO trajectories under {root}"); continue
        bci.STAGE1_ROOT = STAGE1 / stage1_dir
        bci.traj_key_for = (lambda m: (lambda task_id, meta:
            (f"{meta['chain']}__{task_id}_{m}" if meta["condition"] == "dependent"
             else f"{task_id}_{m}")))(model)
        items, skipped = bci.build_items(trajs)
        for it in items:
            it["author_model"] = model
        all_items.extend(items)
        print(f"  {model}: {len(trajs)} trajs -> {len(items)} action items ({len(skipped)} skipped)")
    out = HERE / "outputs" / "all_claim_items.jsonl"
    out.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in all_items) + "\n",
                   encoding="utf-8")
    print(f"\nTotal {len(all_items)} action-claim items -> {out}")


if __name__ == "__main__":
    main()
