#!/usr/bin/env python3
"""Build proposed-requirement claim items for given task(s) across all five v2
author models, reusing build_claim_items.build_items().

Each model lives under a different experiments root / trajectory suffix / stage1
dir, so we monkeypatch the reusable builder per model:
  deepseek_chat / qwen / gemini_flash -> experiments_v2/real
  deepseek_reasoner                   -> experiments_v2 (non-real)
  gpt4o_mini                          -> experiments_v1

Usage:  python build_task_items.py PR-2 S-5    # -> outputs/<task>_claim_items.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import build_claim_items as bci

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[2]
STAGE1 = RESEARCH / "eval_v3-1_claim2action" / "stage1"

# model -> (experiments root, trajectory filename suffix, stage1 results dir)
MODELS = {
    "deepseek_chat":    ("experiments_v2/real", "_deepseek_deepseek_chat", "results_deepseek_chat"),
    "deepseek_reasoner":("experiments_v2",      "_deepseek_deepseek_reasoner", "results_deepseek_reasoner"),
    "gemini_flash":     ("experiments_v2/real", "_gemini_vertexai_hs3645_gemini_3_flash_preview", "results_gemini_flash"),
    "gpt4o_mini":       ("experiments_v1",      "_openai_gpt_4o_mini", "results_gpt4o_mini"),
    "qwen":             ("experiments_v2/real", "_qwen_qwen3_8b", "results_qwen"),
}


def _generic_metadata(traj_path: Path) -> dict[str, str]:
    """condition/domain/chain from any experiments layout (not just real)."""
    parts = traj_path.parts
    for i, p in enumerate(parts):
        if p in ("independent", "dependent"):
            cond = p
            domain = parts[i + 1] if i + 1 < len(parts) else "unknown"
            chain = parts[i + 2] if cond == "dependent" and i + 2 < len(parts) else "single"
            return {"condition": cond, "domain": domain, "chain": chain}
    return {"condition": "independent", "domain": "unknown", "chain": "single"}


def find_traj(root: str, suffix: str, task: str) -> Path | None:
    base = RESEARCH / root
    hits = list(base.glob(f"independent/*/trajectories/{task}{suffix}.json"))
    return hits[0] if hits else None


def main() -> None:
    tasks = sys.argv[1:] or ["PR-2", "S-5"]
    bci.infer_real_metadata = _generic_metadata  # generic for all roots
    for task in tasks:
        all_items: list[dict] = []
        for model, (root, suffix, stage1_dir) in MODELS.items():
            traj = find_traj(root, suffix, task)
            if traj is None:
                print(f"  [{task}] {model}: no trajectory"); continue
            bci.STAGE1_ROOT = STAGE1 / stage1_dir
            bci.traj_key_for = (lambda m: (lambda task_id, meta:
                (f"{meta['chain']}__{task_id}_{m}" if meta["condition"] == "dependent"
                 else f"{task_id}_{m}")))(model)
            items, skipped = bci.build_items([traj])
            for it in items:
                it["author_model"] = model
            all_items.extend(items)
            note = "; ".join(s["reason"] for s in skipped) or "ok"
            print(f"  [{task}] {model}: {len(items)} items ({note})")
        out = HERE / "outputs" / f"{task}_claim_items.jsonl"
        out.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in all_items) + "\n",
                       encoding="utf-8")
        print(f"  -> {out}  ({len(all_items)} total)\n")


if __name__ == "__main__":
    main()
