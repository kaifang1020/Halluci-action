"""
Build a self-contained Stage 2 annotation web page.

Takes a gold Stage-1 annotation markdown (the claim set + types) plus the
trajectory it references, and bakes the claims, the routed evidence (exactly
what the Stage 2 judge sees), the full trajectory, the slim audit, the
codebook, the tool registry, and the verification guideline into ONE html
file with no external dependencies.

Email that single html to an annotator. They open it in any browser, label
each claim, and click "Export gold" to download a `<task>_gold.json` that
matches the `stage2_verdict_v1` schema and plugs straight into the eval.

Usage:
  # From a gold Stage-1 md (recommended — gives C5-S1-C1 style claim ids):
  python -m research.eval_v3.stage2.annotator.build_annotator \
      --stage1-md research/annotations/v2/C-1_deepseek.md \
      --out research/eval_v3/stage2/annotator/dist/C-1_annotator.html

  # Build for several tasks at once:
  python -m research.eval_v3.stage2.annotator.build_annotator \
      --stage1-md research/annotations/v2/C-1_deepseek.md \
                  research/annotations/v2/D-5_deepseek_r02.md \
                  research/annotations/v2/H-2_deepseek.md

  # Emit only the data bundle (reuse with the standalone template.html):
  python -m research.eval_v3.stage2.annotator.build_annotator \
      --stage1-md research/annotations/v2/C-1_deepseek.md --bundle-only
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from research.eval_v3.stage2.preprocess import (
    BASE,
    CODEBOOK_PATH,
    build_task_header,
    load_audit,
    load_codebook,
    load_tool_registry,
    load_trajectory,
    route_evidence,
    slim_audit,
    slim_tool_calls,
    slim_tool_results,
)

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "template.html"
GUIDELINE_PATH = BASE / "annotations/v2/stage2/stage2_claim_verfication_guideline.md"
DIST = HERE / "dist"

# Stage-1 markdown emits these for the four verifiable types.
_VERIFIABLE = {"action_intention", "action_completion", "observation", "constraint_or_policy"}


def _grab(label: str, text: str) -> str | None:
    """Pull the backticked path that follows a `Label:` line at the top of the md."""
    m = re.search(rf"{re.escape(label)}\s*\n+`([^`]+)`", text)
    return m.group(1).strip() if m else None


def parse_stage1_md(md_path: Path) -> tuple[str, list[dict]]:
    """Return (trajectory_relpath, claims[]). Each claim: claim_id, step_id,
    span, type, validation_scope. Only requires_validation: yes are kept."""
    text = md_path.read_text(encoding="utf-8")
    traj_rel = _grab("Trajectory file:", text)
    if not traj_rel:
        raise ValueError(f"Could not find 'Trajectory file:' backtick path in {md_path}")

    claims: list[dict] = []
    # Split into "## Step N" sections.
    step_sections = re.split(r"\n##\s+Step\s+(\d+)\s*\n", text)
    # step_sections = [preamble, "1", body1, "2", body2, ...]
    for i in range(1, len(step_sections), 2):
        step_id = int(step_sections[i])
        body = step_sections[i + 1]
        # Each claim block starts at "#### <ID>" and runs to the next "####"/"##".
        blocks = re.split(r"\n####\s+", body)
        for blk in blocks[1:]:
            lines = blk.splitlines()
            claim_id = lines[0].strip()
            span = _field(blk, "Span")
            ctype = _field(blk, "Type")
            req = (_field(blk, "Requires validation") or "").lower()
            scope = _field(blk, "Validation scope") or ""
            if req != "yes":
                continue
            if ctype not in _VERIFIABLE:
                continue
            claims.append({
                "claim_id": claim_id,
                "step_id": step_id,
                "span": span or "",
                "type": ctype,
                "validation_scope": scope,
            })
    return traj_rel, claims


def _field(block: str, name: str) -> str | None:
    """Read a `Name: value` field within a claim block (value may be backticked)."""
    m = re.search(rf"^{re.escape(name)}:\s*(.+)$", block, re.MULTILINE)
    if not m:
        return None
    val = m.group(1).strip()
    bt = re.match(r"`(.*)`$", val)
    return bt.group(1) if bt else val


def build_bundle(md_path: Path) -> dict:
    traj_rel, claims = parse_stage1_md(md_path)
    traj_path = (md_path.parent / traj_rel).resolve()
    if not traj_path.exists():
        # md paths are repo-relative; fall back to BASE.
        traj_path = (BASE / traj_rel.replace("research/", "", 1)).resolve()
    if not traj_path.exists():
        raise FileNotFoundError(f"Trajectory not found: {traj_rel}")

    traj = load_trajectory(traj_path)
    audit = load_audit(traj, traj_path)

    task_header = build_task_header(traj)
    tool_calls = slim_tool_calls(traj)
    tool_results = slim_tool_results(traj)
    audit_recs = slim_audit(audit)
    codebook = load_codebook()
    tool_registry = load_tool_registry()

    # Per-claim routed channels (evidence itself is recomputed client-side from
    # the full steps/audit so the bundle stays small and the context panes work).
    for c in claims:
        channels, _ = route_evidence(
            c["type"], c["validation_scope"], c["step_id"],
            tool_calls=tool_calls, tool_results=tool_results, audit_recs=audit_recs,
            codebook=codebook, tool_registry=tool_registry,
        )
        c["routed_channels"] = channels

    steps = [{
        "step_id": s["step_id"],
        "assistant_text": s.get("assistant_text") or "",
        "tool_calls": [{"call_id": t.get("call_id"), "tool_name": t.get("tool_name"),
                        "parameters": t.get("parameters")} for t in (s.get("tool_calls") or [])],
        "tool_results": [{"call_id": t.get("call_id"), "tool_name": t.get("tool_name"),
                          "parameters": t.get("parameters"), "result": t.get("result")}
                         for t in (s.get("tool_results") or [])],
    } for s in traj.get("steps", [])]

    return {
        "task_id": traj.get("task_id"),
        "trajectory_file": traj_rel,
        "schema_version": "stage2_verdict_v1",
        "task_header": task_header,
        "task": traj.get("task"),
        "guideline": GUIDELINE_PATH.read_text(encoding="utf-8") if GUIDELINE_PATH.exists() else "",
        "codebook": codebook,
        "tool_registry": tool_registry,
        "steps": steps,
        "audit": audit_recs,
        "claims": claims,
    }


def _inject(bundle: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    # Escape so the JSON can't break out of the <script> or the HTML parser.
    payload = (json.dumps(bundle, ensure_ascii=False)
               .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
    line = "window.__BUNDLE__ = null; /* __BUNDLE_INJECTION__ */"
    if line not in template:
        raise RuntimeError("Injection marker not found in template.html")
    return template.replace(line, f"window.__BUNDLE__ = {payload};")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage1-md", type=Path, nargs="+", required=True,
                   help="One or more gold Stage-1 annotation markdown files.")
    p.add_argument("--out", type=Path, default=None,
                   help="Output html (single md only). Default dist/<task>_annotator.html.")
    p.add_argument("--bundle-only", action="store_true",
                   help="Write the data bundle JSON instead of a baked html.")
    args = p.parse_args()

    DIST.mkdir(parents=True, exist_ok=True)
    for md in args.stage1_md:
        bundle = build_bundle(md)
        task = bundle["task_id"] or md.stem
        n = len(bundle["claims"])
        by_type: dict[str, int] = {}
        for c in bundle["claims"]:
            by_type[c["type"]] = by_type.get(c["type"], 0) + 1

        if args.bundle_only:
            out = args.out or (DIST / f"{task}_bundle.json")
            out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            out = (args.out if (args.out and len(args.stage1_md) == 1)
                   else DIST / f"{task}_annotator.html")
            out.write_text(_inject(bundle), encoding="utf-8")

        kb = out.stat().st_size / 1024
        print(f"{task}: {n} claims {by_type}  →  {out}  ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
