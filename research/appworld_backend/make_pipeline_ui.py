"""
Full-pipeline review UI for one AppWorld Halluci-Action task — findings-first.

Layout (top → bottom), designed to reduce scan load:
  1. compact score row  — HAR / precision / recall
  2. FINDINGS           — ONLY the items the pipeline flagged, in plain English
                          (over-claims, silent actions, with required-miss / covert
                           highlighted). Usually a handful of cards, not the whole run.
  3. Full trajectory    — collapsed by default (<details>); every claim + action per
                          step for those who want to verify.

Signals shown are the DIRECT judge outputs (human-verifiable):
  claim2action verdict (supported / not_supported),
  proposed_requirement status (required / … / forbidden),
  action-centric said? + requirement_status.
Severity: required-miss = required ∧ not_supported; covert = silent ∧ forbidden.

No external assets — open the .html straight in a browser.

Usage: see the flags in main(); pass --har/--precision/--recall from run_har_metrics.py.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _span(claim: Any) -> str:
    return str(claim.get("span") if isinstance(claim, dict) else (claim or ""))


V_COLOR = {"supported": ("#0a7d33", "#e6f5ec"), "not_supported": ("#b3261e", "#fdecea"),
           "needs_broader_context": ("#8a6d00", "#fff6d9")}
R_COLOR = {"required": ("#1d4ed8", "#e5edff"), "forbidden": ("#b3261e", "#fdecea"),
           "allowed_supporting": ("#555", "#eee"), "unnecessary": ("#777", "#f0f0f0"),
           "unclear": ("#8a6d00", "#fff6d9")}


def _badge(text, colors):
    fg, bg = colors
    return f'<span class="badge" style="color:{fg};background:{bg}">{html.escape(str(text))}</span>'


def _step_of(action_id: str) -> int:
    return int(str(action_id).split("_")[0].replace("step", "") or 0)


def build(task_id, task, model, traj, c2a_preproc, c2a_verdicts, requirement, action_centric,
          har, prec, recall):
    verdict = {v["claim_id"]: v.get("verdict") for v in c2a_verdicts}
    req_by_claim = {r["claim_id"]: r.get("requirement_status") for r in requirement}

    # ---- findings (direct, human-verifiable signals) ----
    over_claims, silent = [], []
    for rec in c2a_preproc:
        cid = rec["claim_id"]
        if verdict.get(cid) == "not_supported":
            rq = req_by_claim.get(cid)
            over_claims.append({"cid": cid, "step": rec["step_id"], "span": _span(rec.get("claim")),
                                "req": rq, "miss": rq == "required"})
    for a in action_centric:
        if a.get("said") is False:
            silent.append({"aid": a["action_id"], "step": _step_of(a["action_id"]),
                           "tool": a.get("tool_name"), "req": a.get("requirement_status"),
                           "covert": a.get("requirement_status") == "forbidden",
                           "reason": a.get("requirement_reason", "")})
    n_miss = sum(1 for x in over_claims if x["miss"])
    n_covert = sum(1 for x in silent if x["covert"])

    def stat(label, val, tone=""):
        return f'<div class="stat {tone}"><div class="v">{val}</div><div class="l">{html.escape(label)}</div></div>'

    scores = "".join([
        stat("HAR", f"{har:.3f}" if har is not None else "—", "hero"),
        stat("C2A precision", f"{prec:.2f}" if prec is not None else "—"),
        stat("A2C recall", f"{recall:.2f}" if recall is not None else "—"),
    ])
    counts = "".join([
        stat("over-claims", len(over_claims), "warn" if over_claims else "ok"),
        stat("silent actions", len(silent), "warn" if silent else "ok"),
        stat("required-miss", n_miss, "bad" if n_miss else "ok"),
        stat("covert", n_covert, "bad" if n_covert else "ok"),
    ])

    # ---- findings cards ----
    fcards = []
    if over_claims:
        items = ""
        for x in over_claims:
            tag = '<span class="sev miss">REQUIRED-MISS</span>' if x["miss"] else '<span class="sev mild">over-claim</span>'
            items += (f'<div class="fitem"><div class="floc">Step {x["step"]}</div>'
                      f'<div class="fbody">“{html.escape(x["span"])}”'
                      f'<div class="fsub">claim2action: <b>not_supported</b> · requirement: '
                      f'<b>{html.escape(str(x["req"]))}</b></div></div>{tag}</div>')
        fcards.append(f'<div class="fcard"><h3>Said, but not done <span class="c">({len(over_claims)})</span></h3>'
                      f'<p class="cap">The agent claimed an action there is no backing tool call for. '
                      f'A <b>required</b> one is a required-miss.</p>{items}</div>')
    if silent:
        items = ""
        for x in silent:
            tag = '<span class="sev miss">COVERT</span>' if x["covert"] else '<span class="sev mild">silent</span>'
            items += (f'<div class="fitem"><div class="floc">Step {x["step"]}</div>'
                      f'<div class="fbody"><code>{html.escape(str(x["tool"]))}</code>'
                      f'<div class="fsub">requirement: <b>{html.escape(str(x["req"]))}</b>'
                      + (f' — {html.escape(x["reason"][:160])}' if x["reason"] else '') + '</div></div>'
                      f'{tag}</div>')
        fcards.append(f'<div class="fcard"><h3>Did, but not said <span class="c">({len(silent)})</span></h3>'
                      f'<p class="cap">The agent executed an action no sentence narrates. '
                      f'A <b>forbidden</b> one is covert.</p>{items}</div>')
    if not fcards:
        fcards.append('<div class="fcard ok"><h3>No halluci-action flagged</h3>'
                      '<p class="cap">Every claim had a backing action and every action was narrated.</p></div>')
    findings = "\n".join(fcards)

    # ---- full trajectory (collapsed) ----
    claims_by_step, acts_by_step = {}, {}
    for rec in c2a_preproc:
        claims_by_step.setdefault(int(rec["step_id"]), []).append(rec)
    for a in action_centric:
        acts_by_step.setdefault(_step_of(a["action_id"]), []).append(a)
    steps_html = []
    for s in traj.get("steps", []):
        sid = int(s["step_id"])
        steps_html.append(f'<div class="step"><div class="sh"><span class="sn">Step {sid}</span>'
                          f'<span class="st">{html.escape(s.get("assistant_text") or "")}</span></div>')
        for rec in claims_by_step.get(sid, []):
            v = verdict.get(rec["claim_id"]); rq = req_by_claim.get(rec["claim_id"])
            steps_html.append(
                f'<div class="row claim"><span class="dir">CLAIM→act</span>'
                f'<span class="txt">“{html.escape(_span(rec.get("claim")))}”</span><span class="tags">'
                + (_badge(v, V_COLOR.get(v, ("#444", "#eee"))) if v else "")
                + (_badge(rq, R_COLOR.get(rq, ("#444", "#eee"))) if rq else "") + '</span></div>')
        for a in acts_by_step.get(sid, []):
            rq = a.get("requirement_status"); said = a.get("said")
            steps_html.append(
                f'<div class="row action"><span class="dir">act→CLAIM</span>'
                f'<span class="txt"><code>{html.escape(a.get("tool_name",""))}</code></span><span class="tags">'
                + _badge("said" if said else "SILENT", ("#0a7d33", "#e6f5ec") if said else ("#b3261e", "#fdecea"))
                + (_badge(rq, R_COLOR.get(rq, ("#444", "#eee"))) if rq else "") + '</span></div>')
        steps_html.append('</div>')

    return TEMPLATE.format(
        task_id=html.escape(task_id), task=html.escape(task or ""), model=html.escape(model or ""),
        scores=scores, counts=counts, findings=findings, steps="\n".join(steps_html),
    )


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Halluci-Action — {task_id}</title>
<style>
  body{{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#f6f6f8;color:#1a1a1a}}
  header{{background:#fff;border-bottom:1px solid #e3e3e6;padding:16px 24px}}
  header h1{{font-size:15px;margin:0 0 3px;font-weight:600}}
  header .meta{{font-size:12px;color:#666;margin-bottom:12px}}
  .stats{{display:flex;gap:9px;flex-wrap:wrap;align-items:stretch}}
  .stats .sep{{width:1px;background:#e6e6ea;margin:2px 4px}}
  .stat{{background:#fafafa;border:1px solid #e6e6ea;border-radius:9px;padding:7px 13px;min-width:72px}}
  .stat .v{{font-size:19px;font-weight:700}} .stat .l{{font-size:10.5px;color:#777;margin-top:2px}}
  .stat.hero{{background:#eef3ff;border-color:#cdddff}} .stat.hero .v{{color:#1d4ed8}}
  .stat.warn .v{{color:#8a6d00}} .stat.bad{{background:#fdecea;border-color:#f3c2bd}} .stat.bad .v{{color:#b3261e}}
  .stat.ok .v{{color:#9aa}}
  main{{max-width:820px;margin:0 auto;padding:20px 24px 80px}}
  .fcard{{background:#fff;border:1px solid #e6e6ea;border-radius:11px;padding:14px 16px;margin-bottom:14px}}
  .fcard.ok{{background:#f0f8f2;border-color:#cfe8d6}}
  .fcard h3{{margin:0 0 2px;font-size:14px}} .fcard h3 .c{{color:#999;font-weight:500}}
  .fcard .cap{{margin:0 0 11px;font-size:12px;color:#777}}
  .fitem{{display:flex;gap:11px;align-items:flex-start;padding:9px 0;border-top:1px solid #f0f0f2}}
  .floc{{font-size:11px;font-weight:700;color:#3730a3;white-space:nowrap;padding-top:2px;width:48px}}
  .fbody{{flex:1;font-size:13.5px;line-height:1.45}}
  .fsub{{font-size:11.5px;color:#888;margin-top:3px}} .fsub b{{color:#555}}
  .fbody code{{background:#eef;padding:1px 6px;border-radius:4px;font-size:12.5px}}
  .sev{{font-size:10px;font-weight:800;padding:2px 8px;border-radius:5px;white-space:nowrap;letter-spacing:.03em;height:fit-content}}
  .sev.miss{{color:#fff;background:#b3261e}} .sev.mild{{color:#8a6d00;background:#fff6d9}}
  details{{margin-top:8px}} summary{{cursor:pointer;font-size:13px;color:#3730a3;font-weight:600;padding:8px 0}}
  .step{{margin:10px 0;background:#fff;border:1px solid #e9e9ec;border-radius:9px;overflow:hidden}}
  .sh{{padding:8px 13px;background:#fbfbfc;border-bottom:1px solid #eee;display:flex;gap:9px;align-items:baseline}}
  .sn{{font-weight:700;font-size:12.5px;color:#3730a3;white-space:nowrap}} .st{{font-size:12px;color:#666;font-style:italic}}
  .row{{display:flex;gap:9px;align-items:flex-start;padding:6px 13px;border-top:1px solid #f2f2f4;font-size:12.5px}}
  .row.action{{background:#fcfcfd}}
  .dir{{font-size:9px;font-weight:700;white-space:nowrap;width:64px;padding-top:2px;letter-spacing:.02em}}
  .row.claim .dir{{color:#7c6fd6}} .row.action .dir{{color:#c58a3a}}
  .txt{{flex:1;line-height:1.4}} .txt code{{background:#eef;padding:1px 5px;border-radius:4px}}
  .tags{{display:flex;gap:5px;align-items:center;flex-wrap:wrap;justify-content:flex-end}}
  .badge{{font-size:10px;font-weight:700;padding:1px 7px;border-radius:5px;white-space:nowrap}}
</style></head><body>
<h2 class="sr-only" style="position:absolute;left:-9999px">Halluci-Action pipeline findings for AppWorld task {task_id}.</h2>
<header>
  <h1>{task}</h1>
  <div class="meta">task_id: {task_id} · model: {model} · judged against the answer key (test_data), no codebook</div>
  <div class="stats">{scores}<div class="sep"></div>{counts}</div>
</header>
<main>
  {findings}
  <details>
    <summary>▸ Full trajectory — every claim &amp; action, step by step</summary>
    {steps}
  </details>
</main></body></html>"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task-id", required=True)
    p.add_argument("--trajectory", type=Path, required=True)
    p.add_argument("--c2a-preproc", type=Path, required=True)
    p.add_argument("--c2a-verdicts", type=Path, required=True)
    p.add_argument("--requirement", type=Path, required=True)
    p.add_argument("--action-centric", type=Path, required=True)
    p.add_argument("--har", type=float, default=None)
    p.add_argument("--precision", type=float, default=None)
    p.add_argument("--recall", type=float, default=None)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    traj = json.loads(args.trajectory.read_text(encoding="utf-8"))
    page = build(args.task_id, traj.get("task"), traj.get("model"), traj,
                 _jsonl(args.c2a_preproc), _jsonl(args.c2a_verdicts),
                 _jsonl(args.requirement), _jsonl(args.action_centric),
                 args.har, args.precision, args.recall)
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
