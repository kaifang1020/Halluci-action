"""
Self-contained claim/action review UI for AppWorld Halluci-Action runs.

Joins the four pipeline artifacts for ONE run into a single offline HTML page:

  trajectory  (assistant_text per step)
  stage-1     (claims per step)          [optional, for step context]
  preproc     (claim + routed evidence)  -> the per-claim rows
  verdicts    (supported / not_supported / needs_broader_context + reason)

The page shows every claim (not only failures), colour-coded by verdict, with
the routed evidence (tool_calls / tool_results / audit state_delta / codebook)
collapsible next to each one, plus a "show only not_supported" filter. No
external assets — open the .html straight in a browser.

Usage (from the halluci repo root, any python):
    python research/appworld_backend/make_review_ui.py \
        --preproc  research/appworld_backend/runs/stage2_2e9b91e_1_preproc.jsonl \
        --verdicts research/appworld_backend/runs/stage2_2e9b91e_1_verdicts.jsonl \
        --trajectory research/appworld_backend/runs/trajectories/2E9B91E-1_deepseek_deepseek_chat.json \
        --out research/appworld_backend/runs/review_2e9b91e_1.html
"""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _claim_span(claim: Any) -> str:
    if isinstance(claim, dict):
        return str(claim.get("span") or claim.get("text") or "")
    return str(claim or "")


def _claim_type(rec: dict[str, Any]) -> str:
    claim = rec.get("claim")
    if isinstance(claim, dict) and claim.get("type"):
        return str(claim["type"])
    return str(rec.get("claim_type") or rec.get("type") or "—")


_VERDICT_STYLE = {
    "supported": ("#0a7d33", "#e6f5ec", "supported"),
    "not_supported": ("#b3261e", "#fdecea", "NOT SUPPORTED"),
    "needs_broader_context": ("#8a6d00", "#fff6d9", "needs broader context"),
    "parse_error": ("#666", "#eee", "parse error"),
    "api_error": ("#666", "#eee", "api error"),
}


def build_html(
    preproc: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
    trajectory: dict[str, Any] | None,
) -> str:
    v_by_id = {v["claim_id"]: v for v in verdicts}
    task = ""
    model = ""
    traj_id = ""
    if trajectory:
        task = trajectory.get("task") or ""
        model = trajectory.get("model") or ""
        traj_id = trajectory.get("trajectory_id") or ""
    # assistant text per step for context
    step_text: dict[int, str] = {}
    if trajectory:
        for s in trajectory.get("steps", []):
            step_text[int(s["step_id"])] = s.get("assistant_text") or ""

    counts = Counter(v_by_id.get(r["claim_id"], {}).get("verdict", "missing") for r in preproc)
    total = len(preproc)
    ns = counts.get("not_supported", 0)
    ns_rate = (ns / total) if total else 0.0

    rows_html: list[str] = []
    last_step = None
    for rec in preproc:
        cid = rec["claim_id"]
        short = cid.split("__")[-1]
        step = rec.get("step_id")
        ctype = _claim_type(rec)
        span = _claim_span(rec.get("claim"))
        channels = rec.get("routed_channels") or []
        evidence = rec.get("evidence") or {}
        v = v_by_id.get(cid, {})
        verdict = v.get("verdict", "missing")
        reason = v.get("reason", "")
        color, bg, label = _VERDICT_STYLE.get(verdict, ("#444", "#eee", verdict))

        # step separator with the assistant text for that step
        if step != last_step:
            txt = html.escape(step_text.get(step, ""))
            rows_html.append(
                f'<div class="stephdr"><span class="stepnum">Step {step}</span>'
                f'<span class="steptext">{txt}</span></div>'
            )
            last_step = step

        ev_json = html.escape(json.dumps(evidence, ensure_ascii=False, indent=2))
        rows_html.append(
            f'<div class="claim {verdict}" data-verdict="{verdict}">'
            f'<div class="chead">'
            f'<span class="badge" style="color:{color};background:{bg}">{html.escape(label)}</span>'
            f'<span class="ctype">{html.escape(ctype)}</span>'
            f'<span class="cid">{html.escape(short)}</span>'
            f'<span class="chan">{html.escape(", ".join(channels))}</span>'
            f'</div>'
            f'<div class="cspan">“{html.escape(span)}”</div>'
            f'<div class="reason"><b>judge:</b> {html.escape(reason)}</div>'
            f'<details><summary>routed evidence</summary><pre>{ev_json}</pre></details>'
            f'</div>'
        )

    summary_bits = " · ".join(
        f'<span class="pill {k}">{k}: {counts.get(k,0)}</span>'
        for k in ["supported", "not_supported", "needs_broader_context"]
        if counts.get(k)
    )

    return _TEMPLATE.format(
        task=html.escape(str(task)),
        model=html.escape(str(model)),
        traj_id=html.escape(str(traj_id)),
        total=total,
        ns=ns,
        ns_rate=f"{ns_rate:.0%}",
        summary=summary_bits,
        rows="\n".join(rows_html),
    )


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claim/Action review — {traj_id}</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; background:#f7f7f8; color:#1a1a1a; }}
  header {{ position:sticky; top:0; background:#fff; border-bottom:1px solid #e2e2e5;
           padding:14px 22px; z-index:5; }}
  header h1 {{ font-size:15px; margin:0 0 4px; font-weight:600; }}
  header .meta {{ font-size:12px; color:#666; }}
  header .stats {{ margin-top:8px; font-size:13px; }}
  .pill {{ display:inline-block; padding:2px 9px; border-radius:20px; margin-right:6px; font-size:12px; }}
  .pill.supported {{ background:#e6f5ec; color:#0a7d33; }}
  .pill.not_supported {{ background:#fdecea; color:#b3261e; }}
  .pill.needs_broader_context {{ background:#fff6d9; color:#8a6d00; }}
  .toolbar {{ margin-top:8px; font-size:13px; }}
  main {{ max-width:920px; margin:0 auto; padding:18px 22px 80px; }}
  .stephdr {{ margin:22px 0 8px; display:flex; gap:10px; align-items:baseline; }}
  .stepnum {{ font-weight:700; font-size:13px; color:#3730a3; white-space:nowrap; }}
  .steptext {{ font-size:12.5px; color:#555; font-style:italic; }}
  .claim {{ background:#fff; border:1px solid #e6e6ea; border-left:4px solid #ccc;
           border-radius:8px; padding:10px 13px; margin:8px 0; }}
  .claim.not_supported {{ border-left-color:#b3261e; }}
  .claim.supported {{ border-left-color:#0a7d33; }}
  .claim.needs_broader_context {{ border-left-color:#8a6d00; }}
  .chead {{ display:flex; gap:9px; align-items:center; font-size:11.5px; color:#777; flex-wrap:wrap; }}
  .badge {{ font-weight:700; padding:1px 8px; border-radius:5px; font-size:11px; }}
  .ctype {{ font-family:ui-monospace,monospace; }}
  .cid {{ color:#aaa; }}
  .chan {{ margin-left:auto; color:#999; font-family:ui-monospace,monospace; }}
  .cspan {{ margin:7px 0 5px; font-size:14px; line-height:1.45; }}
  .reason {{ font-size:12.5px; color:#444; line-height:1.45; }}
  details {{ margin-top:6px; }}
  summary {{ cursor:pointer; font-size:12px; color:#3730a3; }}
  pre {{ background:#0f172a; color:#d7dce8; padding:11px; border-radius:6px; overflow-x:auto;
        font-size:11.5px; line-height:1.4; max-height:340px; }}
  body.only-ns .claim:not(.not_supported) {{ display:none; }}
  body.only-ns .stephdr {{ display:none; }}
</style></head>
<body>
<header>
  <h1>{task}</h1>
  <div class="meta">model: {model} &nbsp;·&nbsp; trajectory: {traj_id}</div>
  <div class="stats">{summary} &nbsp; — &nbsp; {ns}/{total} not_supported ({ns_rate})</div>
  <div class="toolbar">
    <label><input type="checkbox" id="onlyns" onchange="document.body.classList.toggle('only-ns', this.checked)"> show only NOT_SUPPORTED</label>
  </div>
</header>
<main>
{rows}
</main>
</body></html>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preproc", type=Path, required=True)
    p.add_argument("--verdicts", type=Path, required=True)
    p.add_argument("--trajectory", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    preproc = _load_jsonl(args.preproc)
    verdicts = _load_jsonl(args.verdicts)
    trajectory = json.loads(args.trajectory.read_text(encoding="utf-8")) if args.trajectory else None

    html_text = build_html(preproc, verdicts, trajectory)
    args.out.write_text(html_text, encoding="utf-8")
    print(f"Wrote {args.out}  ({len(preproc)} claims)")


if __name__ == "__main__":
    main()
