#!/usr/bin/env python3
"""
Human-annotation UI for ONE complete trajectory's proposed-requirement judge
output. Defaults to D-5 (the fully-judged pilot trajectory, 34 action claims).

For each action claim it shows the judge's requirement_status + reason + the
ground-truth / constraint IDs it cited, plus the task oracle (GT steps,
constraints, ambiguity traps) at the top so the annotator can check the call.
The human can agree or override (required / allowed_supporting / unnecessary /
forbidden / unclear / judge_wrong) with a note. Agreement rate is shown live.

Usage:
  python generate_d5_requirement_annotation_ui.py            # task D-5
  python generate_d5_requirement_annotation_ui.py --task M-4 # any task with preds
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
PREDS = OUT / "d5_requirement_predictions.jsonl"
ITEMS = OUT / "real_claim_items.jsonl"


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def build(task: str, preds_path: Path, items_path: Path = ITEMS) -> dict:
    preds = {p["item_id"]: p for p in load_jsonl(preds_path)}
    items = [i for i in load_jsonl(items_path) if i.get("task_id") == task and i["item_id"] in preds]
    if not items:
        raise SystemExit(f"No predicted claim items for task {task} in {preds_path.name}")
    items.sort(key=lambda i: (i.get("author_model") or "", i.get("step_id") or 0, i["item_id"]))

    td = items[0].get("task_definition") or {}
    gt = [{"id": f"GT-{n+1}", "text": s} for n, s in enumerate(td.get("ground_truth_steps") or [])]
    cons = [{"id": f"C-{n+1}", "text": s} for n, s in enumerate(td.get("system_constraints") or [])]
    traps = td.get("ambiguity_traps") or []

    cards = []
    for it in items:
        p = preds[it["item_id"]]
        cards.append({
            "item_id": it["item_id"],
            "author_model": it.get("author_model"),
            "step_id": it.get("step_id"),
            "claim_type": it.get("claim_type"),
            "claim_span": it.get("claim_span"),
            "context": [s.get("text") for s in (it.get("assistant_context") or [])],
            "judge_status": p.get("requirement_status"),
            "judge_reason": p.get("reason"),
            "judge_conf": p.get("confidence"),
            "basis_gt": p.get("basis_gt_steps") or [],
            "basis_c": p.get("basis_constraints") or [],
        })
    return {
        "task_id": task,
        "task": items[0].get("task"),
        "domain": items[0].get("domain"),
        "condition": items[0].get("condition"),
        "current_datetime": items[0].get("current_datetime"),
        "gt": gt, "constraints": cons, "traps": traps, "cards": cards,
    }


HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Requirement annotation · __TASK__</title>
<style>
 :root{--bg:#f5f6f8;--panel:#fff;--panel2:#eef1f5;--border:#d4d9e0;--text:#1c2330;--muted:#5b6573;--accent:#2563eb;}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
   font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
 header{position:sticky;top:0;z-index:10;background:var(--panel);border-bottom:1px solid var(--border);
   padding:9px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;box-shadow:0 1px 4px rgba(0,0,0,.05)}
 header h1{font-size:15px;margin:0;font-weight:600}.spacer{flex:1}
 .stat{color:var(--muted);font-size:12px}.stat b{color:var(--text)}
 button,select{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:5px 9px;cursor:pointer}
 button:hover{border-color:var(--accent)}
 .wrap{max-width:1050px;margin:0 auto;padding:14px}
 .oracle{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:6px 14px;margin-bottom:14px}
 .oracle summary{cursor:pointer;font-weight:600;padding:6px 0}
 .oracle .row{display:flex;gap:8px;padding:3px 0;font-size:13px;border-bottom:1px solid #f1f3f6}
 .oracle .row:last-child{border:none}
 .gid{font:11px ui-monospace,monospace;min-width:42px;color:#1e40af}
 .cid{font:11px ui-monospace,monospace;min-width:42px;color:#8a4b00}
 .card{background:var(--panel);border:1px solid var(--border);border-radius:10px;margin-bottom:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.04)}
 .card.done{border-color:var(--accent)}.card.disagree{border-color:#d23b3b}
 .chead{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:9px 13px;background:var(--panel2);border-bottom:1px solid var(--border)}
 .chip{font-size:11px;padding:2px 8px;border-radius:999px;background:#e3e8ef;color:var(--muted);border:1px solid var(--border)}
 .idx{color:var(--muted);font-size:12px}
 .st-required{color:#fff;background:#b00}.st-forbidden{color:#fff;background:#7a0099}
 .st-allowed_supporting{color:#0b5a52;background:#cdeee9}.st-unnecessary{color:#555;background:#e3e8ef}.st-unclear{color:#8a6500;background:#fbeec2}
 .body{padding:11px 13px}.lab{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin:8px 0 3px}
 .claim{font-size:15px;font-weight:600}
 .judge{border:1px solid var(--border);border-radius:8px;background:#fbfcfd;padding:9px 11px;margin-top:8px}
 .basis{display:flex;gap:6px;flex-wrap:wrap;margin-top:5px}
 .bchip{font:11px ui-monospace,monospace;padding:1px 7px;border-radius:5px;background:#dbe6ff;color:#1e40af}
 .bchip.c{background:#ffedcf;color:#8a4b00}
 details.ctx summary{cursor:pointer;color:var(--muted);font-size:13px;margin-top:8px}
 .ctx .s{padding:2px 0;border-bottom:1px dashed #eef1f5;font-size:13px}.ctx .s:last-child{border:none}
 .ctrls{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:10px 13px;border-top:1px solid var(--border)}
 .ob{font-size:12px;padding:5px 8px} .ob.on{color:#fff;border-color:var(--accent);background:var(--accent)}
 .ob.wrong.on{background:#d23b3b;border-color:#d23b3b}
 .note{flex:1;min-width:160px}.note input{width:100%;padding:6px 9px;border:1px solid var(--border);border-radius:6px;font:inherit}
 .agree{font-size:11px;padding:2px 8px;border-radius:999px}.agree.y{background:#d6f3e2;color:#0f7a40}.agree.n{background:#fbdcdc;color:#a82424}
</style></head><body>
<header>
 <h1>Requirement annotation · <span id="tt"></span></h1>
 <span class="stat"><b id="s-done">0</b>/<b id="s-tot">0</b> done</span>
 <span class="stat">agree judge <b id="s-agree">0</b> · override <b id="s-over">0</b></span>
 <span class="spacer"></span>
 <select id="fm"><option value="">all models</option></select>
 <select id="f"><option value="">all</option><option value="todo">un-annotated</option>
   <option value="disagree">disagreements</option></select>
 <button id="exp">Export</button>
</header>
<div class="wrap">
 <div id="task"></div>
 <div id="list"></div>
</div>
<script>
const D=__DATA__, KEY="req_annot_"+D.task_id;
let A={};try{A=JSON.parse(localStorage.getItem(KEY))||{}}catch(e){A={}}
function save(){localStorage.setItem(KEY,JSON.stringify(A));head()}
function esc(s){const d=document.createElement("div");d.textContent=s==null?"":String(s);return d.innerHTML}
const STATUSES=["required","allowed_supporting","unnecessary","forbidden","unclear"];

document.getElementById("tt").textContent=D.task_id;
(function task(){
  const gt=D.gt.map(g=>`<div class="row"><span class="gid">${g.id}</span><span>${esc(g.text)}</span></div>`).join("");
  const c=D.constraints.map(x=>`<div class="row"><span class="cid">${x.id}</span><span>${esc(x.text)}</span></div>`).join("");
  const tr=D.traps.map(t=>`<div class="row"><span class="gid">trap</span><span>${esc(t)}</span></div>`).join("");
  document.getElementById("task").innerHTML=
   `<div class="oracle"><div style="font-weight:600;padding:6px 0">Task ${esc(D.task_id)} · ${esc(D.domain)} · ${esc(D.condition)}</div>
     <div style="margin-bottom:6px">${esc(D.task)}</div>
     <details open><summary>Task oracle — ground truth &amp; constraints (what the judge compares against)</summary>
       <div class="lab">Ground truth steps</div>${gt}
       <div class="lab">System constraints</div>${c}
       ${tr?`<div class="lab">Ambiguity traps</div>${tr}`:''}</details></div>`;
})();

function head(){
  let done=0,agree=0,over=0;
  for(const c of D.cards){const a=A[c.item_id]; if(a&&a.v){done++; if(a.v===c.judge_status)agree++; else if(a.v!=="judge_wrong"||true)over++;}}
  // recompute over as done-agree
  over=done-agree;
  document.getElementById("s-done").textContent=done;
  document.getElementById("s-tot").textContent=D.cards.length;
  document.getElementById("s-agree").textContent=agree;
  document.getElementById("s-over").textContent=over;
}
function render(){
  const f=document.getElementById("f").value, fm=document.getElementById("fm").value, list=document.getElementById("list"); list.innerHTML="";
  D.cards.forEach((c,i)=>{
    const a=A[c.item_id]||{}; const done=!!a.v; const disagree=done&&a.v!==c.judge_status;
    if(fm&&c.author_model!==fm)return;
    if(f==="todo"&&done)return; if(f==="disagree"&&!disagree)return;
    const ctx=(c.context||[]).map(t=>`<div class="s">${esc(t)}</div>`).join("");
    const bgt=(c.basis_gt||[]).map(x=>`<span class="bchip">${esc(x)}</span>`).join("");
    const bc=(c.basis_c||[]).map(x=>`<span class="bchip c">${esc(x)}</span>`).join("");
    const card=document.createElement("div"); card.className="card"+(done?" done":"")+(disagree?" disagree":"");
    card.innerHTML=`<div class="chead"><span class="idx">#${i+1}</span>
        ${c.author_model?`<span class="chip" style="color:#1e40af;background:#dbe6ff">${esc(c.author_model)}</span>`:''}
        <span class="chip">step ${esc(c.step_id)}</span>
        <span class="chip">${esc(c.claim_type)}</span>
        <span class="chip st-${c.judge_status}">judge: ${esc(c.judge_status)}</span>
        <span class="chip">conf ${esc(c.judge_conf)}</span>
        ${done?`<span class="agree ${disagree?'n':'y'}">${disagree?'override → '+a.v:'agree'}</span>`:''}</div>
      <div class="body">
        <div class="lab">Claim</div><div class="claim">${esc(c.claim_span)}</div>
        <div class="judge"><div class="lab">Judge reason</div><div>${esc(c.judge_reason)}</div>
          ${(bgt||bc)?`<div class="basis">${bgt}${bc}</div>`:''}</div>
        ${ctx?`<details class="ctx"><summary>nearby assistant context</summary>${ctx}</details>`:''}
      </div>
      <div class="ctrls">
        ${STATUSES.map(s=>`<button class="ob ${a.v===s?'on':''}" data-v="${s}">${s}</button>`).join("")}
        <button class="ob wrong ${a.v==='judge_wrong'?'on':''}" data-v="judge_wrong">judge_wrong</button>
        <span class="note"><input type="text" placeholder="note" value="${esc(a.note||'')}"></span>
      </div>`;
    card.querySelectorAll(".ob").forEach(b=>b.addEventListener("click",()=>{
      const cur=A[c.item_id]||{}; cur.v=(cur.v===b.dataset.v)?null:b.dataset.v; cur.ts=new Date().toISOString();
      A[c.item_id]=cur; save(); render();
    }));
    const inp=card.querySelector(".note input");
    inp.addEventListener("input",()=>{const cur=A[c.item_id]||{};cur.note=inp.value;A[c.item_id]=cur;save()});
    list.appendChild(card);
  });
}
document.getElementById("exp").addEventListener("click",()=>{
  const out=D.cards.map(c=>({item_id:c.item_id,step_id:c.step_id,claim_span:c.claim_span,
    judge_status:c.judge_status,human:(A[c.item_id]||{}).v||null,
    agree:(A[c.item_id]||{}).v? ((A[c.item_id].v===c.judge_status)) : null,
    note:(A[c.item_id]||{}).note||""}));
  const b=new Blob([JSON.stringify(out,null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=`requirement_annotation_${D.task_id}.json`;a.click();
});
(function(){const s=document.getElementById("fm");
  [...new Set(D.cards.map(c=>c.author_model).filter(Boolean))].sort().forEach(m=>{
    const o=document.createElement("option");o.value=m;o.textContent=m;s.appendChild(o);});})();
document.getElementById("fm").addEventListener("change",render);
document.getElementById("f").addEventListener("change",render);
head();render();
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="D-5")
    ap.add_argument("--preds", default=str(PREDS))
    ap.add_argument("--items", default=str(ITEMS))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data = build(args.task, Path(args.preds), Path(args.items))
    html = HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace("__TASK__", args.task)
    dest = Path(args.out) if args.out else OUT / f"requirement_annotation_{args.task}.html"
    dest.write_text(html, encoding="utf-8")
    from collections import Counter
    dist = Counter(c["judge_status"] for c in data["cards"])
    print(f"task {args.task}: {len(data['cards'])} claims | judge dist {dict(dist)}")
    print(f"Wrote {dest}")


if __name__ == "__main__":
    main()
