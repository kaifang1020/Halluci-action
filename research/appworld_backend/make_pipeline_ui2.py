"""Full-pipeline review UI (v2) — TWO AXES SEPARATED.

Fixes the conflation in make_pipeline_ui.py, where a `narrated-but-forbidden`
policy violation (e.g. sending money without confirming) was not surfaced as a
finding, so the header could read "No halluci-action flagged" while the
trajectory showed a `forbidden` action.

The two axes are now rendered as separate, clearly-labelled panels:

  A. FIDELITY axis  (does narration match actions?)
       - over-claim   : a claim with claim2action verdict `not_supported`
       - required-miss: over-claim whose requirement_status is `required`
       - silent action: an executed action no sentence narrates (`said=False`)
     Source: c2a verdicts + the ANSWER-KEY action-centric run.
     HAR / C2A precision / A2C recall belong here.

  B. POLICY axis    (did any action violate the codebook?)
       - forbidden (narrated) : requirement_status `forbidden`, said=True
       - covert               : requirement_status `forbidden`, said=False  (silent AND forbidden)
     Source: the CODEBOOK action-centric run (--action-centric-policy). Optional;
     if omitted, only the fidelity axis is shown.

"No issue flagged" appears only when BOTH axes are clean.

Additive file — the original make_pipeline_ui.py is untouched.

Usage:
    python research/appworld_backend/make_pipeline_ui2.py \
        --task-id 2e9b91e_1 \
        --trajectory        runs/trajectories/2E9B91E-1_deepseek_deepseek_chat_r02.json \
        --c2a-preproc       runs/stage2_2e9b91e_1_r02_v2fix_preproc.jsonl \
        --c2a-verdicts      runs/stage2_2e9b91e_1_r02_v2fix_verdicts.jsonl \
        --requirement       runs/requirement_2e9b91e_1_r02_gtonly.jsonl \
        --action-centric    runs/action_centric_2e9b91e_1_r02_gtonly.jsonl \
        --action-centric-policy runs/action_centric_2e9b91e_1_r02_cb.jsonl \
        --har 1.0 --precision 1.0 --recall 1.0 \
        --out runs/pipeline_2e9b91e_1_r02_v2.html
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _jsonl(p: Path | None) -> list[dict[str, Any]]:
    if p is None or not Path(p).exists():
        return []
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


def _span(claim: Any) -> str:
    return str(claim.get("span") if isinstance(claim, dict) else (claim or ""))


def _step_of(action_id: str) -> int:
    return int(str(action_id).split("_")[0].replace("step", "") or 0)


V_COLOR = {"supported": ("#0a7d33", "#e6f5ec"), "not_supported": ("#b3261e", "#fdecea"),
           "needs_broader_context": ("#8a6d00", "#fff6d9")}
R_COLOR = {"required": ("#1d4ed8", "#e5edff"), "forbidden": ("#b3261e", "#fdecea"),
           "allowed_supporting": ("#555", "#eee"), "unnecessary": ("#777", "#f0f0f0"),
           "unclear": ("#8a6d00", "#fff6d9")}


def _badge(text, colors):
    fg, bg = colors
    return f'<span class="badge" style="color:{fg};background:{bg}">{html.escape(str(text))}</span>'


def _stat(label, val, tone=""):
    return (f'<div class="stat {tone}"><div class="v">{html.escape(str(val))}</div>'
            f'<div class="l">{html.escape(label)}</div></div>')


def build(task_id, task, model, traj, c2a_preproc, c2a_verdicts, requirement,
          action_fidelity, action_policy, har, prec, recall, policy_source,
          har_over=None, har_silent=None):
    verdict = {v["claim_id"]: v.get("verdict") for v in c2a_verdicts}
    req_by_claim = {r["claim_id"]: r.get("requirement_status") for r in requirement}

    # ---------- FIDELITY axis ----------
    over_claims = []
    for rec in c2a_preproc:
        cid = rec["claim_id"]
        if verdict.get(cid) == "not_supported":
            rq = req_by_claim.get(cid)
            over_claims.append({"step": rec["step_id"], "span": _span(rec.get("claim")),
                                "req": rq, "miss": rq == "required"})
    silent = [a for a in action_fidelity if a.get("said") is False]
    n_miss = sum(1 for x in over_claims if x["miss"])

    # ---------- POLICY axis ----------
    policy_viol = [a for a in action_policy if a.get("requirement_status") == "forbidden"]
    covert = [a for a in policy_viol if a.get("said") is False]
    narrated_forbidden = [a for a in policy_viol if a.get("said") is not False]

    # ---------- score rows ----------
    # Dashboard over-claims/silent come from the SAME bipartite metric as precision/recall
    # (run_har_metrics), so the five headline numbers are internally consistent. The finding
    # cards below stay per-claim (not_supported) / per-action (said=False) as readable detail;
    # a note reconciles the two when the 1:1 matching counts more than the per-item verdicts.
    oc_n = har_over if har_over is not None else len(over_claims)
    sil_n = har_silent if har_silent is not None else len(silent)
    fidelity_scores = "".join([
        _stat("HAR", f"{har:.3f}" if har is not None else "—", "hero"),
        _stat("C2A precision", f"{prec:.2f}" if prec is not None else "—"),
        _stat("A2C recall", f"{recall:.2f}" if recall is not None else "—"),
        _stat("over-claims", oc_n, "warn" if oc_n else "ok"),
        _stat("silent", sil_n, "warn" if sil_n else "ok"),
        _stat("required-miss", n_miss, "bad" if n_miss else "ok"),
    ])
    rnotes = []
    if har_over is not None and har_over != len(over_claims):
        d = har_over - len(over_claims)
        rnotes.append(f"HAR's <b>over-claims = {har_over}</b> (bipartite 1:1 claim↔action matching) is {d} "
                      f"more than the {len(over_claims)} card(s) below, which are the per-claim "
                      f"<b>not_supported</b> verdicts. The matching also flags claims it cannot pair to a "
                      f"distinct action (typically repeated identical calls).")
    if har_silent is not None and har_silent != len(silent):
        d = har_silent - len(silent)
        rnotes.append(f"HAR's <b>silent = {har_silent}</b> is {d} more than the {len(silent)} card(s) below "
                      f"(per-action <b>said=False</b>): the matching also flags actions it leaves unpaired "
                      f"(e.g. duplicate calls covered by a single narration sentence).")
    fidelity_note = f'<div class="reconcile">{"<br>".join(rnotes)}</div>' if rnotes else ""
    policy_scores = "".join([
        _stat("forbidden", len(policy_viol), "bad" if policy_viol else "ok"),
        _stat("↳ narrated", len(narrated_forbidden), "warn" if narrated_forbidden else "ok"),
        _stat("↳ covert", len(covert), "bad" if covert else "ok"),
    ]) if action_policy else '<div class="muted">no policy pass supplied (run action-centric with --codebook)</div>'

    # ---------- FIDELITY findings ----------
    fcards = []
    if over_claims:
        items = ""
        for x in over_claims:
            tag = ('<span class="sev miss">REQUIRED-MISS</span>' if x["miss"]
                   else '<span class="sev mild">over-claim</span>')
            items += (f'<div class="fitem"><div class="floc">Step {x["step"]}</div>'
                      f'<div class="fbody">“{html.escape(x["span"])}”'
                      f'<div class="fsub">claim2action <b>not_supported</b> · requirement '
                      f'<b>{html.escape(str(x["req"]))}</b></div></div>{tag}</div>')
        fcards.append(f'<div class="fcard"><h3>Said, but not done <span class="c">({len(over_claims)})</span></h3>'
                      f'<p class="cap">A claim with no backing tool call. A <b>required</b> one is a required-miss.</p>{items}</div>')
    if silent:
        items = ""
        for a in silent:
            items += (f'<div class="fitem"><div class="floc">Step {_step_of(a["action_id"])}</div>'
                      f'<div class="fbody"><code>{html.escape(str(a.get("tool_name")))}</code>'
                      f'<div class="fsub">executed but no sentence narrates it</div></div>'
                      f'<span class="sev mild">silent</span></div>')
        fcards.append(f'<div class="fcard"><h3>Did, but not said <span class="c">({len(silent)})</span></h3>'
                      f'<p class="cap">An action no assistant sentence narrates.</p>{items}</div>')
    if not fcards:
        fcards.append('<div class="fcard ok"><h3>Fidelity clean</h3>'
                      '<p class="cap">Every claim had a backing action and every action was narrated.</p></div>')
    fidelity_findings = "\n".join(fcards)

    # ---------- POLICY findings ----------
    pcards = []
    if not action_policy:
        pcards.append('<div class="fcard muted2"><h3>No policy pass</h3>'
                      '<p class="cap">Run the action-centric judge with <code>--codebook</code> and pass it as '
                      '<code>--action-centric-policy</code> to audit codebook violations.</p></div>')
    elif policy_viol:
        items = ""
        for a in policy_viol:
            covert_it = a.get("said") is False
            tag = ('<span class="sev miss">COVERT</span>' if covert_it
                   else '<span class="sev fbd">forbidden</span>')
            items += (f'<div class="fitem"><div class="floc">Step {_step_of(a["action_id"])}</div>'
                      f'<div class="fbody"><code>{html.escape(str(a.get("tool_name")))}</code>'
                      f'<div class="fsub">{"SILENT · " if covert_it else "narrated · "}'
                      f'basis <b>{html.escape(str(a.get("requirement_basis")))}</b>'
                      + (f' — {html.escape((a.get("requirement_reason") or "")[:160])}' if a.get("requirement_reason") else '')
                      + '</div></div>' + tag + '</div>')
        pcards.append(f'<div class="fcard"><h3>Policy violations <span class="c">({len(policy_viol)})</span></h3>'
                      f'<p class="cap">Actions the codebook forbids. Silent + forbidden = <b>covert</b> '
                      f'(invisible to the fidelity axis).</p>{items}</div>')
    else:
        pcards.append('<div class="fcard ok"><h3>Policy clean</h3>'
                      '<p class="cap">No action violated a codebook rule.</p></div>')
    policy_findings = "\n".join(pcards)

    # ---------- full trajectory ----------
    claims_by_step, acts_by_step = {}, {}
    for rec in c2a_preproc:
        claims_by_step.setdefault(int(rec["step_id"]), []).append(rec)
    policy_status = {a["action_id"]: a.get("requirement_status") for a in action_policy}
    for a in action_fidelity:
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
            said = a.get("said")
            pol = policy_status.get(a["action_id"])  # codebook verdict, shown separately
            steps_html.append(
                f'<div class="row action"><span class="dir">act→CLAIM</span>'
                f'<span class="txt"><code>{html.escape(a.get("tool_name",""))}</code></span><span class="tags">'
                + _badge("said" if said else "SILENT", ("#0a7d33", "#e6f5ec") if said else ("#b3261e", "#fdecea"))
                + (_badge(f"policy:{pol}", R_COLOR.get(pol, ("#444", "#eee"))) if pol else "") + '</span></div>')
        steps_html.append('</div>')

    return TEMPLATE.format(
        task_id=html.escape(task_id), task=html.escape(task or ""), model=html.escape(model or ""),
        policy_source=html.escape(policy_source or "none"),
        fidelity_scores=fidelity_scores, fidelity_note=fidelity_note, policy_scores=policy_scores,
        fidelity_findings=fidelity_findings, policy_findings=policy_findings,
        steps="\n".join(steps_html),
    )


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Halluci-Action — {task_id}</title>
<style>
  body{{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#f6f6f8;color:#1a1a1a}}
  header{{background:#fff;border-bottom:1px solid #e3e3e6;padding:16px 24px}}
  header h1{{font-size:15px;margin:0 0 3px;font-weight:600}}
  header .meta{{font-size:12px;color:#666;margin-bottom:6px}}
  .axis{{max-width:840px;margin:0 auto;padding:2px 24px}}
  .axishead{{font-size:12px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#3730a3;margin:20px 0 8px}}
  .axishead.pol{{color:#b3261e}}
  .axissub{{font-size:11.5px;color:#888;font-weight:500;text-transform:none;letter-spacing:0}}
  .stats{{display:flex;gap:9px;flex-wrap:wrap;align-items:stretch}}
  .stat{{background:#fafafa;border:1px solid #e6e6ea;border-radius:9px;padding:7px 13px;min-width:64px}}
  .stat .v{{font-size:19px;font-weight:700}} .stat .l{{font-size:10.5px;color:#777;margin-top:2px}}
  .stat.hero{{background:#eef3ff;border-color:#cdddff}} .stat.hero .v{{color:#1d4ed8}}
  .stat.warn .v{{color:#8a6d00}} .stat.bad{{background:#fdecea;border-color:#f3c2bd}} .stat.bad .v{{color:#b3261e}}
  .stat.ok .v{{color:#9aa}}
  .muted{{font-size:12px;color:#999;padding:8px 2px}}
  .reconcile{{font-size:11px;color:#8a6d00;background:#fff8e6;border:1px solid #f0e0a8;border-radius:7px;padding:7px 11px;margin-top:8px;line-height:1.5;max-width:840px}}
  .reconcile b{{color:#6b5500}}
  main{{max-width:840px;margin:0 auto;padding:8px 24px 80px}}
  .fcard{{background:#fff;border:1px solid #e6e6ea;border-radius:11px;padding:14px 16px;margin-bottom:12px}}
  .fcard.ok{{background:#f0f8f2;border-color:#cfe8d6}} .fcard.muted2{{background:#f7f7f8;border-color:#e6e6ea}}
  .fcard h3{{margin:0 0 2px;font-size:14px}} .fcard h3 .c{{color:#999;font-weight:500}}
  .fcard .cap{{margin:0 0 11px;font-size:12px;color:#777}}
  .fitem{{display:flex;gap:11px;align-items:flex-start;padding:9px 0;border-top:1px solid #f0f0f2}}
  .floc{{font-size:11px;font-weight:700;color:#3730a3;white-space:nowrap;padding-top:2px;width:48px}}
  .fbody{{flex:1;font-size:13.5px;line-height:1.45}}
  .fsub{{font-size:11.5px;color:#888;margin-top:3px}} .fsub b{{color:#555}}
  .fbody code{{background:#eef;padding:1px 6px;border-radius:4px;font-size:12.5px}}
  .sev{{font-size:10px;font-weight:800;padding:2px 8px;border-radius:5px;white-space:nowrap;letter-spacing:.03em;height:fit-content}}
  .sev.miss{{color:#fff;background:#b3261e}} .sev.mild{{color:#8a6d00;background:#fff6d9}} .sev.fbd{{color:#fff;background:#d1453b}}
  details{{margin-top:14px}} summary{{cursor:pointer;font-size:13px;color:#3730a3;font-weight:600;padding:8px 0}}
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
<header>
  <h1>{task}</h1>
  <div class="meta">task_id: {task_id} · model: {model}</div>
  <div class="meta">Two independent axes. <b>Fidelity</b> = does narration match actions (answer-key). <b>Policy</b> = did any action break the codebook (source: {policy_source}).</div>
</header>
<main>
  <div class="axis"><div class="axishead">A · Fidelity axis <span class="axissub">— claim ↔ action match (answer key)</span></div>
    <div class="stats">{fidelity_scores}</div>{fidelity_note}</div>
  {fidelity_findings}
  <div class="axis"><div class="axishead pol">B · Policy axis <span class="axissub">— codebook compliance</span></div>
    <div class="stats">{policy_scores}</div></div>
  {policy_findings}
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
    p.add_argument("--action-centric", type=Path, required=True,
                   help="ANSWER-KEY action-centric (fidelity axis: said + required)")
    p.add_argument("--action-centric-policy", type=Path, default=None,
                   help="CODEBOOK action-centric (policy axis: forbidden). Optional.")
    p.add_argument("--policy-source", default=None,
                   help="Label for where the policy verdicts came from, e.g. 'codebook.md'.")
    p.add_argument("--har", type=float, default=None)
    p.add_argument("--precision", type=float, default=None)
    p.add_argument("--recall", type=float, default=None)
    p.add_argument("--over-claims", type=int, default=None,
                   help="bipartite over-claim count from run_har_metrics (keeps dashboard consistent with precision)")
    p.add_argument("--silent", type=int, default=None,
                   help="bipartite silent-action count from run_har_metrics (keeps dashboard consistent with recall)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    traj = json.loads(args.trajectory.read_text(encoding="utf-8"))
    policy_source = args.policy_source or (args.action_centric_policy.name if args.action_centric_policy else "none")
    page = build(args.task_id, traj.get("task"), traj.get("model"), traj,
                 _jsonl(args.c2a_preproc), _jsonl(args.c2a_verdicts), _jsonl(args.requirement),
                 _jsonl(args.action_centric), _jsonl(args.action_centric_policy),
                 args.har, args.precision, args.recall, policy_source,
                 args.over_claims, args.silent)
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
