"""Build BLIND human-labeling worksheets for the judge-reliability study.

Reads runs/validation/manifest.json (from gen_validation_data.py) and emits, for a
random (seeded) sample of items, worksheets that bundle enough evidence for a human
to label WITHOUT seeing the judge's guess (no anchoring):

  * fidelity : one row per unique claim  -> human_verdict ∈ {supported, not_supported}
      evidence = claim span + the tool calls/results in scope (+ codebook for policy
      claims) + the step text it came from.
  * action   : one row per unique action -> human_said ∈ {true,false}
                                            human_requirement_status ∈ {required,
                                            allowed_supporting, unnecessary, forbidden}
      evidence = the tool call (name+params) + the FULL narration (to judge `said`)
      + the task answer key (to judge requirement_status).

Outputs (runs/validation/):
  worksheet_fidelity.jsonl   worksheet_action.jsonl     (blind; label fields empty)
  label_worksheet.html       (open in a browser; click labels; Download -> *.labels.jsonl)

Merge the downloaded labels back and score with check_judge_appworld.py.

Deterministic: fixed seed so re-running yields the same sample/order.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

BASE = Path(__file__).resolve().parent
VAL = BASE / "runs" / "validation"
CODEBOOK = BASE / "codebook.md"
SEED = 20260718


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _truncate(v, n=280) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …"


# ---------- fidelity items (from s2preproc: claim + routed evidence) ----------

def build_fidelity_items(manifest: list[dict]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for cell in manifest:
        pre = Path(cell["s2preproc"])
        if not pre.exists():
            continue
        for r in _load_jsonl(pre):
            cid = r["claim_id"]
            if cid in seen:
                continue
            seen.add(cid)
            ev = r.get("evidence") or {}
            tcs = [{"tool_name": t.get("tool_name"), "parameters": t.get("parameters")}
                   for t in (ev.get("tool_calls") or [])]
            trs = [{"tool_name": t.get("tool_name"), "result": _truncate(t.get("result"))}
                   for t in (ev.get("tool_results") or [])]
            items.append({
                "item_id": cid,
                "kind": "fidelity",
                "task_id": cell["task_id"],
                "agent_model": cell["agent_model"],
                "task_instruction": (r.get("task_header") or {}).get("task"),
                "claim_span": r["claim"]["span"],
                "claim_type": r["claim"]["type"],
                "validation_scope": r["claim"].get("validation_scope"),
                "evidence_tool_calls": tcs,
                "evidence_tool_results": trs,
                "evidence_claim_context": _truncate(ev.get("claim_context"), 600),
                "is_policy_claim": bool(ev.get("codebook")),
                "human_verdict": "",
            })
    return items


# ---------- action items (from trajectory + one action file + answer key) ----------

def build_action_items(manifest: list[dict]) -> list[dict]:
    from ground_truth_util import load_ground_truth_outcomes
    items: list[dict] = []
    seen: set[str] = set()
    for cell in manifest:
        act_paths = cell.get("action") or {}
        if not act_paths:
            continue
        one = Path(next(iter(act_paths.values())))  # any judge file: same action set
        traj = json.loads(Path(cell["trajectory"]).read_text(encoding="utf-8"))
        narration = "\n".join(f"[step {s.get('step_id')}] {s.get('assistant_text') or ''}"
                              for s in traj.get("steps") or [])
        # map action_id -> params from trajectory (build_action_items uses step<K>_action<J>)
        call_params: dict[str, dict] = {}
        for s in traj.get("steps") or []:
            for j, tc in enumerate(s.get("tool_calls") or []):
                call_params[f"step{s.get('step_id')}_action{j}"] = tc.get("parameters") or {}
        try:
            answer_key = [g["text"] for g in load_ground_truth_outcomes(cell["task_id"])]
        except Exception:
            answer_key = []
        for a in _load_jsonl(one):
            aid = f"{cell['cell']}::{a.get('action_id')}"
            if aid in seen:
                continue
            seen.add(aid)
            items.append({
                "item_id": aid,
                "kind": "action",
                "task_id": cell["task_id"],
                "agent_model": cell["agent_model"],
                "action_id": a.get("action_id"),
                "task_instruction": traj.get("task"),
                "tool_name": a.get("tool_name"),
                "parameters": call_params.get(a.get("action_id"), {}),
                "answer_key": answer_key,
                "narration": narration,
                "human_said": "",
                "human_requirement_status": "",
            })
    return items


# ---------- HTML labeler ----------

def _html(fid: list[dict], act: list[dict], codebook_text: str) -> str:
    data = {"fidelity": fid, "action": act, "codebook": codebook_text}
    payload = json.dumps(data, ensure_ascii=False)
    # NOTE: kept dependency-free; opens from file://. Labels download as JSONL.
    return """<!doctype html><html><head><meta charset="utf-8">
<title>Judge reliability — labeling worksheet</title>
<style>
 body{font:15px/1.6 -apple-system,system-ui,sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#1a1a1a}
 h1{font-size:20px} .bar{position:sticky;top:0;background:#fff;padding:10px 0;border-bottom:1px solid #ddd;z-index:5}
 .card{border:1px solid #e2e2e2;border-radius:8px;padding:14px 16px;margin:14px 0}
 .meta{color:#777;font-size:12.5px;margin-bottom:6px}
 .claim{background:#f6f6f4;border-left:3px solid #7F77DD;padding:8px 12px;border-radius:4px;margin:6px 0;white-space:pre-wrap}
 .ev{font-size:13px;color:#333;margin:6px 0} .ev code{background:#f0f0ee;padding:1px 5px;border-radius:3px}
 details{margin:6px 0} summary{cursor:pointer;color:#555;font-size:13px}
 pre{background:#f6f6f4;padding:8px;border-radius:4px;overflow-x:auto;font-size:12.5px;white-space:pre-wrap}
 .opts label{display:inline-block;margin-right:14px;cursor:pointer;padding:4px 8px;border:1px solid #ccc;border-radius:6px}
 .opts input{margin-right:5px} .done{border-color:#1D9E75;background:#f2fbf7}
 button{font-size:15px;padding:8px 16px;border-radius:8px;border:1px solid #7F77DD;background:#7F77DD;color:#fff;cursor:pointer}
 .kpi{font-weight:500}
</style></head><body>
<h1>Judge reliability — labeling worksheet</h1>
<p>Label each item <b>on your own judgment</b>. The judge's guess is hidden on purpose.
When done (or partway), click <b>Download labels</b> and send me the file.</p>
<div class="bar"><span class="kpi" id="prog">0 / 0</span> &nbsp;
 <button onclick="dl()">⬇ Download labels</button> &nbsp;
 <label style="font-size:13px;color:#555"><input type="checkbox" id="hideDone" onchange="render()"> hide finished</label>
 <details style="display:inline-block;margin-left:12px"><summary>codebook</summary><pre id="cb"></pre></details>
</div>
<div id="list"></div>
<script>
const DATA = __PAYLOAD__;
const ANS = {};
document.getElementById('cb').textContent = DATA.codebook;
const FID_OPTS = ["supported","not_supported"];
const SAID_OPTS = ["true","false"];
const REQ_OPTS = ["required","allowed_supporting","unnecessary","forbidden"];
function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function opt(id,field,val,cur){const on=cur===val?'checked':'';
 return `<label><input type=radio name="${id}:${field}" value="${val}" ${on} onchange="set('${id}','${field}','${val}')">${val}</label>`;}
function fidCard(it){
 let ev='';
 if(it.evidence_tool_calls.length) ev+=`<div class=ev>🛠 tool calls: `+it.evidence_tool_calls.map(t=>`<code>${esc(t.tool_name)}(${esc(JSON.stringify(t.parameters))})</code>`).join(' ')+`</div>`;
 if(it.evidence_tool_results.length) ev+=`<div class=ev>📥 results: `+it.evidence_tool_results.map(t=>`<code>${esc(t.tool_name)}</code> → ${esc(t.result)}`).join('<br>')+`</div>`;
 if(it.is_policy_claim) ev+=`<div class=ev>📕 policy claim — check the wording against the codebook (top-right).</div>`;
 if(it.evidence_claim_context) ev+=`<details><summary>step text</summary><pre>${esc(it.evidence_claim_context)}</pre></details>`;
 const cur=ANS[it.item_id]?ANS[it.item_id].human_verdict:'';
 return `<div class="card ${cur?'done':''}"><div class=meta>${esc(it.task_id)} · ${esc(it.agent_model)} · ${esc(it.claim_type)} · ${esc(it.item_id)}</div>
  <div class=claim>“${esc(it.claim_span)}”</div>${ev}
  <div class=opts><b>supported?</b> ${FID_OPTS.map(v=>opt(it.item_id,'human_verdict',v,cur)).join('')}</div></div>`;}
function actCard(it){
 const s=ANS[it.item_id]||{};
 return `<div class="card ${(s.human_said&&s.human_requirement_status)?'done':''}"><div class=meta>${esc(it.task_id)} · ${esc(it.agent_model)} · ${esc(it.item_id)}</div>
  <div class=ev>⚙ action: <code>${esc(it.tool_name)}(${esc(JSON.stringify(it.parameters))})</code></div>
  <details><summary>answer key (${it.answer_key.length})</summary><pre>${esc(it.answer_key.join('\\n'))}</pre></details>
  <details><summary>full narration (to judge “said”)</summary><pre>${esc(it.narration)}</pre></details>
  <div class=opts><b>narrated (said)?</b> ${SAID_OPTS.map(v=>opt(it.item_id,'human_said',v,s.human_said||'')).join('')}</div>
  <div class=opts style="margin-top:6px"><b>requirement:</b> ${REQ_OPTS.map(v=>opt(it.item_id,'human_requirement_status',v,s.human_requirement_status||'')).join('')}</div></div>`;}
function set(id,field,val){(ANS[id]=ANS[id]||{})[field]=val; ANS[id].item_id=id; prog(); }
function done(it){if(it.kind==='fidelity')return ANS[it.item_id]&&ANS[it.item_id].human_verdict;
 return ANS[it.item_id]&&ANS[it.item_id].human_said&&ANS[it.item_id].human_requirement_status;}
function prog(){const all=DATA.fidelity.concat(DATA.action);const d=all.filter(done).length;
 document.getElementById('prog').textContent=d+' / '+all.length+' labeled';}
function render(){const hide=document.getElementById('hideDone').checked;
 const all=[['Fidelity — is the claim supported?',DATA.fidelity,fidCard],['Actions — said? + requirement',DATA.action,actCard]];
 document.getElementById('list').innerHTML=all.map(([h,arr,fn])=>{
  const cards=arr.filter(it=>!(hide&&done(it))).map(fn).join('');
  return `<h2>${h}</h2>`+ (cards||'<p style=color:#999>all labeled ✓</p>');}).join('');
 prog();}
function dl(){const lines=Object.values(ANS).filter(a=>a.item_id).map(a=>JSON.stringify(a));
 const blob=new Blob([lines.join('\\n')+'\\n'],{type:'application/x-ndjson'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='worksheet.labels.jsonl';a.click();}
render();
</script></body></html>""".replace("__PAYLOAD__", payload)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", type=Path, default=VAL / "manifest.json")
    p.add_argument("--n-fidelity", type=int, default=0, help="0 = all claims (shuffled); N = random sample of N")
    p.add_argument("--n-action", type=int, default=0, help="0 = all actions")
    args = p.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    fid = build_fidelity_items(manifest)
    act = build_action_items(manifest)
    rng.shuffle(fid)
    rng.shuffle(act)
    if args.n_fidelity:
        fid = fid[:args.n_fidelity]
    if args.n_action:
        act = act[:args.n_action]

    (VAL / "worksheet_fidelity.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in fid) + "\n", encoding="utf-8")
    (VAL / "worksheet_action.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in act) + "\n", encoding="utf-8")
    html = _html(fid, act, CODEBOOK.read_text(encoding="utf-8"))
    (VAL / "label_worksheet.html").write_text(html, encoding="utf-8")

    npol = sum(1 for x in fid if x["claim_type"] == "constraint_or_policy")
    print(f"fidelity items: {len(fid)}  ({npol} policy claims)")
    print(f"action items  : {len(act)}")
    print(f"  -> {VAL / 'worksheet_fidelity.jsonl'}")
    print(f"  -> {VAL / 'worksheet_action.jsonl'}")
    print(f"  -> {VAL / 'label_worksheet.html'}  (open in a browser to label)")


if __name__ == "__main__":
    main()
