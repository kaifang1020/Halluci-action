#!/usr/bin/env python3
"""
Build a single HTML UI to audit every *unsupported* signal that feeds the
halluci-action metrics, in BOTH directions, so a human can check whether the
rates are inflated:

  - claim2action (stage2): claims judged not_supported
      * over-claim  (claim_type action_intention / action_completion)  -> feeds ①
      * fabrication (claim_type observation / constraint_or_policy)     -> feeds ④
    NBC verdicts are folded in using the human review (human_review/).

  - action2claim (stage3): tool calls with said=false  -> feeds ②
      * silent-read  (is_mutation = false)   — usually benign (un-narrated search)
      * silent-write (is_mutation = true)    — the meaningful "did but didn't say"
      * covert       (said=false ∧ requirement_status = forbidden)

Filter by model and direction/category; mark each case agree / misjudged /
unsure (+ note); a live panel recomputes the per-model rates as you flag
misjudged cases, so you can see directly how much is "虚高".

Usage:  python generate_unsupported_review_ui.py   # -> unsupported_review_ui.html
"""
from __future__ import annotations

import json
from pathlib import Path

import generate_nbc_review_ui as g  # reuse stage2 helpers (same dir)

HERE = g.HERE
STAGE3_OUT = HERE.parent.parent / "eval_v3-2_action2claim" / "stage3_action_annotation" / "outputs"
HUMAN_FINAL = HERE / "human_review" / "nbc_human_final.json"

# stage2 author label -> stage3 enriched file stem
MODELS = {
    "deepseek_chat": "real_deepseek",
    "deepseek_reasoner": "deepseek_reasoner",
    "gemini_flash": "gemini_flash",
    "gpt4o_mini": "openai_gpt_4o_mini",
    "qwen": "qwen",
}
ACTION_TYPES = {"action_intention", "action_completion"}
FACT_TYPES = {"observation", "constraint_or_policy"}


def _human_map() -> dict[str, str]:
    """claim_id -> resolved verdict (supported/not_supported) from human review."""
    out = {}
    if HUMAN_FINAL.exists():
        for c in json.loads(HUMAN_FINAL.read_text(encoding="utf-8")):
            v = c.get("human_verdict")
            out[c["claim_id"]] = "not_supported" if v == "unsupported" else "supported"
    return out


def _result_status(tool_result) -> str:
    """Pull a short status (success/error/blocked) out of a stage3 tool_result."""
    if not isinstance(tool_result, dict):
        return ""
    r = tool_result.get("result", tool_result)
    if isinstance(r, dict):
        st = r.get("status")
        if isinstance(r.get("data"), dict) and r["data"].get("status"):
            return f"{st}/{r['data']['status']}"
        return str(st) if st is not None else ""
    return ""


def collect_claim2action(human: dict[str, str]) -> tuple[list[dict], dict[str, dict]]:
    """not_supported claims (NBC folded via human review) + per-model denominators."""
    cases: list[dict] = []
    denom: dict[str, dict] = {m: {"L": 0, "facts": 0} for m in MODELS}
    for model in MODELS:
        rd = f"binary_results_{model}_v2"
        for jsonl in sorted((HERE / rd).glob("*/*_verdicts.jsonl")):
            split = jsonl.parent.name
            stem = jsonl.name.replace("_verdicts.jsonl", "")
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                ct = rec.get("claim_type")
                v = rec.get("verdict")
                if v == "needs_broader_context":
                    v = human.get(rec["claim_id"])
                    if v is None:
                        continue
                if v not in ("supported", "not_supported"):
                    continue
                # denominators
                if ct in ACTION_TYPES:
                    denom[model]["L"] += 1
                elif ct in FACT_TYPES:
                    denom[model]["facts"] += 1
                if v != "not_supported":
                    continue
                sub = "over_claim" if ct in ACTION_TYPES else (
                    "fabrication" if ct in FACT_TYPES else "other")
                cid = rec["claim_id"]
                step_id = rec.get("step_id")
                _, target_idx = g._claim_idx(cid)
                prompt_path = HERE / rd / "prompts" / split / stem / f"{cid}.md"
                cases.append({
                    "uid": f"c2a::{model}::{cid}",
                    "direction": "claim2action",
                    "category": sub,
                    "model": model,
                    "split": split,
                    "claim_id": cid,
                    "traj_id": rec.get("traj_id"),
                    "step_id": step_id,
                    "claim_type": ct,
                    "claim_span": rec.get("claim_span"),
                    "judge_reason": rec.get("reason"),
                    "evidence_pointer": rec.get("evidence_pointer"),
                    "was_nbc": rec.get("verdict") == "needs_broader_context",
                    "same_step_claims": g._load_same_step_claims(model, split, stem, step_id, target_idx),
                    "tool_calls_in_scope": g._tool_calls_in_scope(
                        rec.get("traj_id"), step_id, rec.get("validation_scope")),
                    "evidence": g._extract_case_section(prompt_path) if prompt_path.exists() else "",
                })
    return cases, denom


def collect_action2claim() -> tuple[list[dict], dict[str, dict]]:
    """said=false actions + per-model denominators (n_actions, n_mutations)."""
    cases: list[dict] = []
    denom: dict[str, dict] = {}
    for model, stem in MODELS.items():
        f = STAGE3_OUT / f"{stem}_action_audit_enriched.jsonl"
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        denom[model] = {"R": len(rows), "n_mut": sum(1 for r in rows if r.get("is_mutation"))}
        for r in rows:
            if r.get("said"):
                continue
            mut = bool(r.get("is_mutation"))
            forbidden = r.get("requirement_status") == "forbidden"
            cat = "covert" if forbidden else ("silent_write" if mut else "silent_read")
            cases.append({
                "uid": f"a2c::{model}::{r.get('item_id')}",
                "direction": "action2claim",
                "category": cat,
                "model": model,
                "split": r.get("condition"),
                "domain": r.get("domain"),
                "task_id": r.get("task_id"),
                "step_id": r.get("step_id"),
                "tool_name": r.get("tool_name"),
                "parameters": r.get("parameters"),
                "result_status": _result_status(r.get("tool_result")),
                "is_mutation": mut,
                "requirement_status": r.get("requirement_status"),
                "relation": r.get("relation"),
                "judge_reason": r.get("said_reason"),
                "assistant_sentences": [s.get("text") for s in (r.get("assistant_sentences") or [])],
            })
    return cases, denom


HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unsupported review · both directions</title>
<style>
 :root{--bg:#f5f6f8;--panel:#fff;--panel2:#eef1f5;--border:#d4d9e0;--text:#1c2330;
       --muted:#5b6573;--accent:#2563eb;--red:#d23b3b;--green:#1a9d54;--amber:#b8860b;}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);
   font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
 header{position:sticky;top:0;z-index:10;background:var(--panel);border-bottom:1px solid var(--border);
   padding:10px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;box-shadow:0 1px 4px rgba(0,0,0,.05)}
 header h1{font-size:15px;margin:0;font-weight:600}
 .spacer{flex:1}.stat{color:var(--muted);font-size:12px}.stat b{color:var(--text)}
 button,select{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--border);
   border-radius:6px;padding:5px 9px;cursor:pointer}
 button:hover{border-color:var(--accent)}
 .wrap{max-width:1150px;margin:0 auto;padding:14px}
 .rates{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:10px 14px;margin-bottom:14px;
   overflow-x:auto}
 table{border-collapse:collapse;font-size:13px;width:100%} th,td{padding:4px 9px;text-align:right;border-bottom:1px solid #eef1f5}
 th:first-child,td:first-child{text-align:left} td.q{color:var(--muted);font-size:11px}
 .filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
 .chip{font-size:11px;padding:2px 8px;border-radius:999px;background:#e3e8ef;color:var(--muted);border:1px solid var(--border)}
 .chip.model{color:#1e40af;background:#dbe6ff}
 .chip.dir-claim2action{color:#7a3b00;background:#ffe6c9}.chip.dir-action2claim{color:#0b5a52;background:#cdeee9}
 .chip.cat-over_claim{color:#8a1c1c;background:#ffe0e0}.chip.cat-fabrication{color:#8a1c1c;background:#ffe0e0}
 .chip.cat-silent_read{color:#555;background:#eceff3}.chip.cat-silent_write{color:#8a4b00;background:#ffedcf}
 .chip.cat-covert{color:#fff;background:#b00}
 .chip.mut{color:#8a4b00;background:#ffedcf}.chip.read{color:#555;background:#eceff3}
 .card{background:var(--panel);border:1px solid var(--border);border-radius:10px;margin-bottom:14px;overflow:hidden;
   box-shadow:0 1px 3px rgba(0,0,0,.04)}
 .card.audited{border-color:var(--accent)}
 .chead{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:9px 13px;background:var(--panel2);
   border-bottom:1px solid var(--border)}
 .idx{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
 .body{padding:11px 13px}.lab{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px}
 .claim{font-size:15px;font-weight:600;margin-bottom:9px}
 .mono{font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
 .reason{color:#3a4453;margin-bottom:9px}
 .said{border:1px solid var(--border);border-radius:8px;background:#fbfcfd;padding:8px 11px;margin-bottom:9px}
 .said .s{padding:2px 0;border-bottom:1px dashed #eef1f5} .said .s:last-child{border:none}
 .clist{border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:9px}
 .crow{display:flex;gap:8px;padding:4px 9px;border-bottom:1px solid #eef1f5;font-size:13px}
 .crow:last-child{border:none}.crow .ci{color:#9aa3b2;font:11px ui-monospace,monospace;min-width:34px}
 .crow.target{background:#fff6da}.crow.target .cspan{font-weight:700;color:#7a5a00}
 .crow.novalidate{opacity:.5}.crow.tnow{background:#eafaf0}
 .tcl .cspan{font:12px ui-monospace,monospace}.tcl b{color:#0f5fbf}
 details{margin-bottom:9px}summary{cursor:pointer;color:var(--muted);font-size:13px}
 pre.ev{margin:6px 0 0;padding:10px;max-height:440px;overflow:auto;white-space:pre-wrap;word-break:break-word;
   background:#fbfcfd;border:1px solid var(--border);border-radius:8px;font:12px/1.5 ui-monospace,monospace;color:#2b3340}
 .ctrls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 13px;border-top:1px solid var(--border)}
 .ab{border-width:1px} .ab[data-v="agree"].on{background:var(--red);color:#fff;border-color:var(--red)}
 .ab[data-v="misjudged"].on{background:var(--green);color:#fff;border-color:var(--green)}
 .ab[data-v="unsure"].on{background:var(--amber);color:#fff;border-color:var(--amber)}
 .note{flex:1;min-width:180px}.note input{width:100%;padding:6px 9px;border:1px solid var(--border);border-radius:6px;font:inherit}
 .meta{color:var(--muted);font-size:11px;padding:0 13px 10px;font-family:ui-monospace,monospace;word-break:break-all}
 .pill{padding:2px 8px;border-radius:999px;font-size:11px}
 .pill.agree{background:#fbdcdc;color:#a82424}.pill.misjudged{background:#d6f3e2;color:#0f7a40}.pill.unsure{background:#fbeec2;color:#8a6500}
</style></head><body>
<header>
 <h1>Unsupported review · both directions</h1>
 <span class="stat">showing <b id="s-shown">0</b> / <b id="s-total">0</b></span>
 <span class="stat">audited <b id="s-aud">0</b> · ✗misjudged <b id="s-mis">0</b></span>
 <span class="spacer"></span>
 <select id="f-model"><option value="">all models</option></select>
 <select id="f-dir"><option value="">both directions</option>
   <option value="claim2action">claim2action (said→done)</option>
   <option value="action2claim">action2claim (done→said)</option></select>
 <select id="f-cat"><option value="">all categories</option>
   <option value="over_claim">① over-claim</option>
   <option value="fabrication">④ fabrication</option>
   <option value="silent_read">② silent-read (benign?)</option>
   <option value="silent_write">② silent-WRITE</option>
   <option value="covert">②⚑ covert</option></select>
 <select id="f-aud"><option value="">all</option><option value="todo">un-audited</option><option value="done">audited</option></select>
 <button id="exp">Export</button>
</header>
<div class="wrap">
 <div class="rates" id="rates"></div>
 <div class="filters">
   <span class="stat">Mark each: <b style="color:var(--red)">agree</b> = really unsupported ·
   <b style="color:var(--green)">misjudged</b> = 虚高/judge wrong · unsure. Rates panel updates live (misjudged removed from numerators). Auto-saved to this browser.</span>
 </div>
 <div id="list"></div>
</div>
<script>
const CASES=__CASES__, DENOM=__DENOM__;
const KEY="unsupported_audit_v1";
let A={}; try{A=JSON.parse(localStorage.getItem(KEY))||{}}catch(e){A={}}
function save(){localStorage.setItem(KEY,JSON.stringify(A));renderRates();renderHead()}
function esc(s){const d=document.createElement("div");d.textContent=s==null?"":String(s);return d.innerHTML}
const MODELS=Object.keys(DENOM.c2a);

function counts(model){
  // numerators among NOT-misjudged cases
  let over=0,fab=0,sread=0,swrite=0,covert=0;
  for(const c of CASES){ if(c.model!==model) continue;
    if((A[c.uid]||{}).v==="misjudged") continue;
    if(c.category==="over_claim")over++;
    else if(c.category==="fabrication")fab++;
    else if(c.category==="silent_read")sread++;
    else if(c.category==="silent_write")swrite++;
    else if(c.category==="covert"){covert++; if(c.is_mutation)swrite++;}
  }
  const L=DENOM.c2a[model].L, facts=DENOM.c2a[model].facts, R=DENOM.a2c[model].R, nmut=DENOM.a2c[model].n_mut;
  const silent_all=sread+swrite+covert - (0); // covert already separate; recompute below
  return {over,fab,sread,swrite,covert,L,facts,R,nmut};
}
function rate(n,d){return d?(n/d):0}
function pct(x){return (x*100).toFixed(1)+"%"}
function f1miss(over,silent){const P=1-over,Rc=1-silent;const F=(P+Rc)?2*P*Rc/(P+Rc):0;return 1-F}

function renderRates(){
  let h=`<table><thead><tr><th>model</th><th>① say-not-done</th><th>④ fabricate</th>
    <th>②all done-not-said</th><th>②write only</th><th>covert</th><th>③ halluci(②all)</th><th>③ halluci(②write)</th></tr></thead><tbody>`;
  for(const m of MODELS){
    const c=counts(m);
    const silentAll=(c.sread+c.swrite+c.covert);   // covert counted once
    const silentAllN = CASES.filter(x=>x.model===m && x.direction==="action2claim" && (A[x.uid]||{}).v!=="misjudged").length;
    const silentWriteN = CASES.filter(x=>x.model===m && x.direction==="action2claim" && (x.is_mutation) && (A[x.uid]||{}).v!=="misjudged").length;
    const over=rate(c.over,c.L), fab=rate(c.fab,c.facts);
    const s_all=rate(silentAllN,c.R), s_w=rate(silentWriteN,c.nmut);
    h+=`<tr><td>${esc(m)}</td>
      <td>${pct(over)}<div class="q">${c.over}/${c.L}</div></td>
      <td>${pct(fab)}<div class="q">${c.fab}/${c.facts}</div></td>
      <td>${pct(s_all)}<div class="q">${silentAllN}/${c.R}</div></td>
      <td>${pct(s_w)}<div class="q">${silentWriteN}/${c.nmut}</div></td>
      <td>${c.covert}</td>
      <td>${pct(f1miss(over,s_all))}</td>
      <td>${pct(f1miss(over,s_w))}</td></tr>`;
  }
  h+="</tbody></table>";
  document.getElementById("rates").innerHTML=h;
}
function renderHead(){
  const tot=CASES.length, aud=Object.values(A).filter(x=>x&&x.v).length;
  const mis=Object.values(A).filter(x=>x&&x.v==="misjudged").length;
  document.getElementById("s-total").textContent=tot;
  document.getElementById("s-aud").textContent=aud;
  document.getElementById("s-mis").textContent=mis;
}
function sentBlock(c){
  if(c.direction!=="action2claim")return "";
  const ss=(c.assistant_sentences||[]);
  const inner = ss.length? ss.map(t=>`<div class="s">${esc(t)}</div>`).join("")
    : `<div class="s" style="color:#a82424">⌀ the agent produced NO text this step (pure silent action)</div>`;
  return `<div class="lab">What the agent SAID around this action (judge said: not disclosed)</div><div class="said">${inner}</div>`;
}
function ctxBlock(c){
  if(!c.same_step_claims||!c.same_step_claims.length)return "";
  const rows=c.same_step_claims.map(s=>`<div class="crow ${s.is_target?'target':''} ${s.requires_validation===false?'novalidate':''}">
     <span class="ci">C${s.idx}</span><span class="ct" style="color:#6b7385;font-size:10px;min-width:120px">${esc(s.type)}</span>
     <span class="cspan">${esc(s.span)}</span></div>`).join("");
  return `<div class="lab">Surrounding claims (➤ = this one)</div><div class="clist">${rows}</div>`;
}
function tcBlock(c){
  if(c.direction!=="claim2action")return "";
  const t=c.tool_calls_in_scope||[];
  const rows=t.length? t.map(x=>`<div class="crow tcl ${x.same_step?'tnow':''}"><span class="ci">s${esc(x.step)}</span>
     <span class="cspan"><b>${esc(x.tool)}</b>(${esc(JSON.stringify(x.params))})</span></div>`).join("")
   : `<div class="crow" style="color:#a82424;font-style:italic">⌀ no tool call in this claim's window</div>`;
  return `<div class="lab">Tool calls in scope</div><div class="clist">${rows}</div>`;
}

function render(){
  const fm=document.getElementById("f-model").value, fd=document.getElementById("f-dir").value,
        fc=document.getElementById("f-cat").value, fa=document.getElementById("f-aud").value;
  const list=document.getElementById("list"); list.innerHTML=""; let shown=0;
  CASES.forEach((c,i)=>{
    if(fm&&c.model!==fm)return; if(fd&&c.direction!==fd)return; if(fc&&c.category!==fc)return;
    const a=A[c.uid]||{}; const done=!!a.v;
    if(fa==="todo"&&done)return; if(fa==="done"&&!done)return;
    shown++;
    const card=document.createElement("div"); card.className="card"+(done?" audited":"");
    let head="";
    if(c.direction==="action2claim"){
      head=`<span class="chip ${c.is_mutation?'mut':'read'}">${c.is_mutation?'WRITE':'read'}</span>
            <span class="chip">${esc(c.requirement_status)}</span>
            ${c.result_status?`<span class="chip">${esc(c.result_status)}</span>`:''}`;
    }else{
      head=`<span class="chip">${esc(c.claim_type)}</span>${c.was_nbc?'<span class="chip">was nbc</span>':''}`;
    }
    let main="";
    if(c.direction==="action2claim"){
      main=`<div class="lab">Action done but NOT said (${esc(c.task_id)} · step ${esc(c.step_id)})</div>
        <div class="claim mono"><b>${esc(c.tool_name)}</b>(${esc(JSON.stringify(c.parameters))})</div>
        <div class="lab">Why judge marked it silent</div><div class="reason">${esc(c.judge_reason)}</div>
        ${sentBlock(c)}`;
    }else{
      main=`<div class="lab">Claim judged not_supported</div><div class="claim">${esc(c.claim_span)}</div>
        <div class="lab">Judge reason</div><div class="reason">${esc(c.judge_reason)}</div>
        ${ctxBlock(c)}${tcBlock(c)}
        ${c.evidence?`<details><summary>Show routed evidence</summary><pre class="ev">${esc(c.evidence)}</pre></details>`:''}`;
    }
    card.innerHTML=`<div class="chead"><span class="idx">#${i+1}</span>
       <span class="chip model">${esc(c.model)}</span>
       <span class="chip dir-${c.direction}">${c.direction}</span>
       <span class="chip cat-${c.category}">${c.category.replace('_','-')}</span>
       ${head}${done?`<span class="pill ${a.v}">${a.v}</span>`:''}</div>
      <div class="body">${main}</div>
      <div class="ctrls">
        <button class="ab ${a.v==='agree'?'on':''}" data-v="agree">✗ agree (really unsupported)</button>
        <button class="ab ${a.v==='misjudged'?'on':''}" data-v="misjudged">✓ misjudged (虚高)</button>
        <button class="ab ${a.v==='unsure'?'on':''}" data-v="unsure">? unsure</button>
        <span class="note"><input type="text" placeholder="note" value="${esc(a.note||'')}"></span></div>
      <div class="meta">${esc(c.uid)}${c.traj_id?' · traj '+esc(c.traj_id):''}${c.domain?' · '+esc(c.domain):''}</div>`;
    card.querySelectorAll(".ab").forEach(b=>b.addEventListener("click",()=>{
      const cur=A[c.uid]||{}; cur.v=(cur.v===b.dataset.v)?null:b.dataset.v; cur.ts=new Date().toISOString();
      A[c.uid]=cur; save(); render();
    }));
    const inp=card.querySelector(".note input");
    inp.addEventListener("input",()=>{const cur=A[c.uid]||{};cur.note=inp.value;A[c.uid]=cur;save()});
    list.appendChild(card);
  });
  document.getElementById("s-shown").textContent=shown;
  if(!shown)list.innerHTML='<p class="stat">No cases match.</p>';
}
document.getElementById("exp").addEventListener("click",()=>{
  const out=CASES.map(c=>({uid:c.uid,model:c.model,direction:c.direction,category:c.category,
    is_mutation:c.is_mutation??null,tool_name:c.tool_name||null,claim_span:c.claim_span||null,
    audit:(A[c.uid]||{}).v||null,note:(A[c.uid]||{}).note||""}));
  const b=new Blob([JSON.stringify(out,null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="unsupported_audit.json";a.click();
});
(function(){const s=document.getElementById("f-model");
  [...new Set(CASES.map(c=>c.model))].sort().forEach(m=>{const o=document.createElement("option");o.value=m;o.textContent=m;s.appendChild(o)});})();
["f-model","f-dir","f-cat","f-aud"].forEach(id=>document.getElementById(id).addEventListener("change",render));
renderRates();renderHead();render();
</script></body></html>"""


def main() -> None:
    human = _human_map()
    c2a, d_c2a = collect_claim2action(human)
    a2c, d_a2c = collect_action2claim()
    cases = c2a + a2c
    denom = {"c2a": d_c2a, "a2c": d_a2c}
    out = HTML.replace("__CASES__", json.dumps(cases, ensure_ascii=False)) \
              .replace("__DENOM__", json.dumps(denom, ensure_ascii=False))
    dest = HERE / "unsupported_review_ui.html"
    dest.write_text(out, encoding="utf-8")

    from collections import Counter
    print(f"claim2action not_supported: {len(c2a)}  ({dict(Counter(c['category'] for c in c2a))})")
    print(f"action2claim said=false:   {len(a2c)}  ({dict(Counter(c['category'] for c in a2c))})")
    print(f"total cases: {len(cases)}")
    print(f"Wrote {dest}")


if __name__ == "__main__":
    main()
