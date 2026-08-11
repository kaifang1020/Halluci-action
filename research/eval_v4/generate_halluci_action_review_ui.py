#!/usr/bin/env python3
"""Build a self-contained HTML review UI over ALL halluci-action instances, for
RQ3 (taxonomy of what/why halluci-action goes wrong).

Two directions, unified into one schema:
  - say-not-done  (claim -> action): not_supported action claims
      source: eval_v4/.../outputs/not_supported_items.jsonl  +  requirement preds
      severity: "required" (required_miss) / "forbidden" / "other"
  - did-not-say   (action -> claim): undisclosed executed actions (said=False)
      source: eval_v3-2/.../outputs/<model>_action_audit_enriched.jsonl
      severity: "forbidden" (covert) / "write" (silent mutation) / "read" (benign)

Filterable by model / domain / complexity(difficulty) / direction / severity.
Per-item category + notes are saved to localStorage and exportable as JSON.
"""
from __future__ import annotations
import json, html
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH.parent))
from research.tasks import TASKS  # noqa: E402

DIFF = {t["id"]: t.get("difficulty") for t in (TASKS.values() if isinstance(TASKS, dict) else TASKS)}

SAY_OUT = HERE / "stage2" / "proposed_requirement" / "outputs"
DO_OUT = RESEARCH / "eval_v3-2_action2claim" / "stage3_action_annotation" / "outputs"
DO_STEMS = {"deepseek_chat": "real_deepseek", "deepseek_reasoner": "deepseek_reasoner",
            "gemini_flash": "gemini_flash", "gpt4o_mini": "openai_gpt_4o_mini", "qwen": "qwen"}


def _jl(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


_TRAJ_CACHE: dict[str, list[dict]] = {}


def all_tool_calls(traj_path: str | None) -> list[dict]:
    """Every tool call in the whole trajectory (step, tool, params, short result),
    so a reviewer can confirm the agent never did the claimed action anywhere."""
    if not traj_path:
        return []
    if traj_path not in _TRAJ_CACHE:
        f = RESEARCH.parent / traj_path  # paths are stored repo-root-relative ("research/...")
        calls: list[dict] = []
        if f.exists():
            o = json.loads(f.read_text())
            for s in o.get("steps", []):
                for tc, tr in zip(s.get("tool_calls") or [], (s.get("tool_results") or []) + [None] * 9):
                    res = (tr or {}).get("result") if isinstance(tr, dict) else None
                    calls.append({"step": s.get("step_id"), "tool": tc.get("tool_name"),
                                  "params": tc.get("parameters"),
                                  "result": json.dumps(res, ensure_ascii=False)[:300] if res is not None else None})
        _TRAJ_CACHE[traj_path] = calls
    return _TRAJ_CACHE[traj_path]


STAGE2_GLOB = RESEARCH / "eval_v3-1_claim2action" / "stage2"


def _stage2_reasons(claim_ids: set[str]) -> dict[str, str]:
    """The 'why not_supported' rationale lives in the stage2 binary verdict files
    (field `reason`), keyed by claim_id — not in the requirement predictions."""
    out: dict[str, str] = {}
    for f in STAGE2_GLOB.glob("binary_results_*_v2/*/*_verdicts.jsonl"):
        for r in _jl(f):
            cid = r.get("claim_id")
            if cid in claim_ids and r.get("reason"):
                out[cid] = r["reason"]
    return out


def build_records() -> list[dict]:
    recs: list[dict] = []
    # ---- SAY side ----
    items = {i["item_id"]: i for i in _jl(SAY_OUT / "not_supported_items.jsonl")}
    preds = {p["item_id"]: p for p in _jl(SAY_OUT / "not_supported_requirement_predictions.jsonl")}
    reasons = _stage2_reasons({i["claim_id"] for i in items.values()})
    for iid, it in items.items():
        p = preds.get(iid, {})
        rs = p.get("requirement_status")
        sev = "required" if rs == "required" else ("forbidden" if rs == "forbidden" else "other")
        ev = it.get("routed_action_evidence") or {}
        tcs = ev.get("tool_calls") or []
        evidence = [{"step": c.get("step_id"), "tool": c.get("tool_name"),
                     "params": c.get("parameters"), "result": c.get("tool_result")} for c in tcs]
        recs.append({
            "direction": "say-not-done", "severity": sev,
            "model": it.get("author_model"), "domain": it.get("domain"),
            "complexity": DIFF.get(it.get("task_id")), "condition": it.get("condition"),
            "task_id": it.get("task_id"), "task": it.get("task"),
            "claim_type": it.get("claim_type"),
            "headline": it.get("claim_span"),
            "context": it.get("assistant_context"),
            "evidence": evidence,
            "requirement_status": rs,
            "judge_reason": reasons.get(it.get("claim_id")),
            "req_reason": p.get("reason"),
            "all_calls": all_tool_calls(it.get("trajectory_path")),
            "all_claims": all_claims(it.get("stage1_path")),
            "judged_cid": it.get("local_claim_id"),
        })
    # ---- DO side ----
    for model, stem in DO_STEMS.items():
        f = DO_OUT / f"{stem}_action_audit_enriched.jsonl"
        if not f.exists():
            continue
        for r in _jl(f):
            if r.get("said") is not False:
                continue
            rs = r.get("requirement_status")
            sev = "forbidden" if rs == "forbidden" else ("write" if r.get("is_mutation") else "read")
            recs.append({
                "direction": "did-not-say", "severity": sev,
                "model": model, "domain": r.get("domain"),
                "complexity": DIFF.get(r.get("task_id")), "condition": r.get("condition"),
                "task_id": r.get("task_id"), "task": r.get("task"),
                "is_mutation": bool(r.get("is_mutation")),
                "headline": f"{r.get('tool_name')}({json.dumps(r.get('parameters'), ensure_ascii=False)})",
                "context": r.get("assistant_sentences"),
                "evidence": [{"step": r.get("step_id"), "tool": r.get("tool_name"),
                              "params": r.get("parameters"), "result": r.get("tool_result")}],
                "requirement_status": rs,
                "judge_reason": r.get("said_reason"),
                "req_reason": r.get("requirement_reason"),
                "disclosure_timing": r.get("disclosure_timing"),
                "authorization": r.get("authorization"),
                "match_ids": r.get("matched_sentence_ids") or [],
                "all_calls": all_tool_calls(r.get("trajectory_path")),
                "all_claims": all_claims(None, model=model, task_id=r.get("task_id"),
                                         condition=r.get("condition"), chain=r.get("chain")),
                "judged_cid": None,
            })
    return recs


STAGE1 = RESEARCH / "eval_v3-1_claim2action" / "stage1"
_CLAIMS_CACHE: dict[str, list[dict]] = {}


def _parse_stage1(f: Path) -> list[dict]:
    """Flatten a stage1 file into [{cid:'S{step}-C{idx}', step, type, span}]."""
    out: list[dict] = []
    if not f or not f.exists():
        return out
    for blk in json.loads(f.read_text()):
        step = blk.get("step_id")
        for idx, c in enumerate(blk.get("claims") or []):
            out.append({"cid": f"S{step}-C{idx}", "step": step,
                        "type": c.get("type"), "span": c.get("span")})
    return out


def all_claims(stage1_path: str | None, model=None, task_id=None, condition=None, chain=None) -> list[dict]:
    """Every claim stage1 extracted from the trajectory. Uses stage1_path when
    present (say side); otherwise derives results_<model>/<cond>/.../<task>."""
    f = None
    if stage1_path:
        f = RESEARCH.parent / stage1_path
    elif model and task_id:
        base = STAGE1 / f"results_{model}"
        cands = list(base.glob(f"**/{task_id}_*_judge.json"))
        if condition:
            pref = [c for c in cands if f"/{condition}/" in str(c)]
            if chain and chain not in ("single", None):
                pref = [c for c in pref if f"/{chain}/" in str(c)] or pref
            cands = pref or cands
        f = cands[0] if cands else None
    key = str(f) if f else f"{model}:{task_id}"
    if key not in _CLAIMS_CACHE:
        _CLAIMS_CACHE[key] = _parse_stage1(f) if f else []
    return _CLAIMS_CACHE[key]


HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Halluci-Action Review (RQ3)</title>
<style>
:root{--bg:#f5f6f8;--card:#ffffff;--mut:#5b6271;--bd:#d8dce3;--acc:#2563eb}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:#1b1f27}
header{position:sticky;top:0;z-index:5;background:#ffffff;border-bottom:1px solid var(--bd);padding:10px 16px}
h1{font-size:16px;margin:0 0 8px;color:#11151c}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
select,input,button{background:#ffffff;color:#1b1f27;border:1px solid var(--bd);border-radius:6px;padding:5px 8px;font-size:13px}
button{cursor:pointer;background:var(--acc);color:#fff;border-color:var(--acc)}.count{color:var(--mut);margin-left:auto}
main{max-width:1100px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px;margin-bottom:14px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.b{font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid var(--bd);color:#3a414f;background:#f0f2f5}
.b.dir-say{background:#fdf0dc;border-color:#e6c084;color:#8a5a0a}.b.dir-do{background:#e2eefb;border-color:#9cc4ee;color:#1a548f}
.b.sev-required,.b.sev-forbidden{background:#fde3e6;border-color:#f0a8b2;color:#a31827}
.b.sev-write{background:#efe6fb;border-color:#c9b0ea;color:#5a3a8a}
.headline{font-size:15px;font-weight:600;margin:6px 0;color:#11151c}
.lbl{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-top:10px}
.ev{background:#f7f8fa;border:1px solid var(--bd);border-radius:6px;padding:8px;white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px;max-height:220px;overflow:auto;color:#26303d}
.ctx{background:#f7f8fa;border:1px solid var(--bd);border-radius:6px;padding:8px;font-size:12.5px;max-height:260px;overflow:auto;color:#26303d}
.stepblk{margin-bottom:8px;padding-left:8px;border-left:3px solid #cfd6e0}
.stepblk:last-child{margin-bottom:0}
.stepn{color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px}
.sent{margin:1px 0}
b.hl{background:#fff2b0;padding:0 2px;border-radius:3px;color:#5a4500;font-weight:700}
.ctag{font-family:ui-monospace,monospace;font-size:10px;color:#7a8190;background:#eef0f3;border-radius:3px;padding:0 4px;margin-right:2px}
.reason{color:#8a5a0a;font-style:italic}
.reason.rq{color:#1a548f}
.alld{margin-top:8px}.alld summary{cursor:pointer;color:var(--acc);font-size:12px;user-select:none}.alld .ev{margin-top:6px}
.annot{display:flex;gap:8px;margin-top:10px;align-items:center}.annot select{flex:0 0 auto}.annot input.note{flex:1}
.dbl-lbl{flex:0 0 auto;white-space:nowrap;font-size:12px;color:#a31827;display:flex;align-items:center;gap:4px;cursor:pointer}
.dblf{display:flex;align-items:center;gap:4px;font-size:13px;color:#a31827;cursor:pointer}
.card.flagged{border-color:#f0a8b2;box-shadow:0 0 0 2px #fde3e6}
.task{color:var(--mut);font-size:12px}
</style></head><body>
<header>
<h1>Halluci-Action Review — RQ3 taxonomy (what / why)</h1>
<div class="filters">
 <select id="f-dir"><option value="">all directions</option><option>say-not-done</option><option>did-not-say</option></select>
 <select id="f-model"></select><select id="f-domain"></select><select id="f-cx"></select>
 <select id="f-sev"><option value="">all severity</option><option>required</option><option>forbidden</option><option>write</option><option>read</option><option>other</option></select>
 <select id="f-acat"><option value="">all my categories</option></select>
 <input id="f-text" placeholder="search text…" style="width:160px">
 <label class="dblf"><input type="checkbox" id="f-dbl"> 🔁 double-check only</label>
 <button id="export">Export annotations</button>
 <span class="count" id="count"></span>
</div></header>
<main id="list"></main>
<script>
const DATA = __DATA__;
const CATS = ["", "fabricated-completion","overclaimed-intent","wrong-target","unverified-assumption",
  "tool-failed-but-claimed","silent-side-effect","silent-mutation","undisclosed-read","other"];
const $=s=>document.querySelector(s);
const key=r=>[r.direction,r.model,r.task_id,r.headline].join("||");
let ann=JSON.parse(localStorage.getItem("ha_ann")||"{}");
function opts(id,vals,label){const el=$(id);el.innerHTML=`<option value="">${label}</option>`+
  [...new Set(vals.filter(Boolean))].sort().map(v=>`<option>${v}</option>`).join("")}
opts("#f-model",DATA.map(r=>r.model),"all models");
opts("#f-domain",DATA.map(r=>r.domain),"all domains");
opts("#f-cx",DATA.map(r=>r.complexity),"all complexity");
function fillAcat(){const used=new Set(CATS.filter(Boolean));
  Object.values(ann).forEach(a=>{if(a&&a.cat)used.add(a.cat);});
  const cur=$("#f-acat").value;
  $("#f-acat").innerHTML='<option value="">all my categories</option>'+
    [...used].sort().map(c=>`<option ${c===cur?'selected':''}>${esc(c)}</option>`).join("");}
function esc(s){return (s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
function fmt(x){return typeof x==="string"?x:JSON.stringify(x,null,1)}
function ctxHtml(r){const c=r.context;if(!c)return"<i>—</i>";if(!Array.isArray(c))return esc(fmt(c));
  const claim=(r.direction==='say-not-done'&&r.headline)?r.headline.trim():null;
  const mids=new Set(r.match_ids||[]);
  const byStep={};c.forEach(s=>{(byStep[s.step_id]=byStep[s.step_id]||[]).push(s)});
  return Object.keys(byStep).sort((a,b)=>a-b).map(st=>{
    const lines=byStep[st].map(s=>{let t=esc(s.text||fmt(s));
      if(claim&&s.text&&s.text.includes(claim)){const ec=esc(claim);t=t.split(ec).join('<b class="hl">'+ec+'</b>');}
      else if(mids.has(s.sentence_id)){t='<b class="hl">'+t+'</b>';}
      return '<div class="sent">'+t+'</div>';}).join("");
    return '<div class="stepblk"><div class="stepn">step '+esc(st)+'</div>'+lines+'</div>';
  }).join("");}
function claimsHtml(r){const cs=r.all_claims;if(!cs||!cs.length)return"<i>— no claims extracted —</i>";
  const byStep={};cs.forEach(c=>{(byStep[c.step]=byStep[c.step]||[]).push(c)});
  return Object.keys(byStep).sort((a,b)=>a-b).map(st=>{
    const lines=byStep[st].map(c=>{const j=(c.cid===r.judged_cid);
      const tag='<span class="ctag">'+esc(c.cid)+' · '+esc(c.type)+'</span> ';
      const sp=j?'<b class="hl">'+esc(c.span)+'</b>':esc(c.span);
      return '<div class="sent">'+tag+sp+'</div>';}).join("");
    return '<div class="stepblk"><div class="stepn">step '+esc(st)+'</div>'+lines+'</div>';}).join("");}
function evHtml(ev){if(!ev||!ev.length)return"<i>— no in-scope tool calls —</i>";
  return ev.map(e=>`<b>step ${esc(e.step)}</b> ${esc(e.tool)}(${esc(fmt(e.params))})\\n→ ${esc(fmt(e.result)).slice(0,600)}`).join("\\n\\n")}
function render(){
  const fd=$("#f-dir").value,fm=$("#f-model").value,fo=$("#f-domain").value,fc=$("#f-cx").value,
        fs=$("#f-sev").value,ft=$("#f-text").value.toLowerCase();
  const fdbl=$("#f-dbl").checked,fac=$("#f-acat").value;
  const rows=DATA.filter(r=>(!fd||r.direction===fd)&&(!fm||r.model===fm)&&(!fo||r.domain===fo)
    &&(!fc||r.complexity===fc)&&(!fs||r.severity===fs)
    &&(!fdbl||(ann[key(r)]||{}).dblcheck)
    &&(!fac||(ann[key(r)]||{}).cat===fac)
    &&(!ft||JSON.stringify(r).toLowerCase().includes(ft)));
  $("#count").textContent=rows.length+" / "+DATA.length;
  $("#list").innerHTML=rows.map(r=>{const k=key(r),a=ann[k]||{};
    return `<div class="card${a.dblcheck?' flagged':''}">
    <div class="badges">
      <span class="b ${r.direction==='say-not-done'?'dir-say':'dir-do'}">${r.direction}</span>
      <span class="b sev-${r.severity}">${r.severity}</span>
      <span class="b">${esc(r.model)}</span><span class="b">${esc(r.domain)}</span>
      <span class="b">${esc(r.complexity)}</span><span class="b">${esc(r.task_id)}</span>
      <span class="b">${esc(r.condition)}</span></div>
    <div class="headline">${esc(r.headline)}</div>
    <div class="task">Task: ${esc(r.task)}</div>
    <div class="lbl">assistant context (what it said) — judged claim in <b class="hl">bold</b></div><div class="ctx">${ctxHtml(r)}</div>
    <details class="alld"><summary>all claims in trajectory (${(r.all_claims||[]).length})</summary><div class="ctx">${claimsHtml(r)}</div></details>
    <div class="lbl">behavioral evidence — in-scope tool calls (what the judge routed)</div><div class="ev">${evHtml(r.evidence)}</div>
    <details class="alld"><summary>all tool calls in trajectory (${(r.all_calls||[]).length})</summary><div class="ev">${evHtml(r.all_calls)}</div></details>
    <div class="lbl">judge reason (why not-supported / not-disclosed)</div><div class="reason">${esc(r.judge_reason)||"—"}</div>
    <div class="lbl">requirement verdict — why <b>${esc(r.requirement_status)||"?"}</b></div><div class="reason rq">${esc(r.req_reason)||"—"}</div>
    <div class="annot">
      <select data-k="${esc(k)}" class="cat">${CATS.map(c=>`<option ${a.cat===c?'selected':''}>${c}</option>`).join("")}</select>
      <input class="note" data-k="${esc(k)}" placeholder="why / how — cause attribution, real-life analogy…" value="${esc(a.note||'')}">
      <label class="dbl-lbl"><input type="checkbox" class="dbl" data-k="${esc(k)}" ${a.dblcheck?'checked':''}> 🔁 double-check</label>
    </div></div>`}).join("");
}
function saveAnn(e){const k=e.target.dataset.k;if(!k)return;
  ann[k]=ann[k]||{};
  if(e.target.classList.contains("cat")){ann[k].cat=e.target.value;fillAcat();}
  else if(e.target.classList.contains("dbl")){ann[k].dblcheck=e.target.checked;
    const card=e.target.closest(".card");if(card)card.classList.toggle("flagged",e.target.checked);}
  else ann[k].note=e.target.value;
  localStorage.setItem("ha_ann",JSON.stringify(ann));}
$("#list").addEventListener("input",saveAnn);
$("#list").addEventListener("change",saveAnn);
["#f-dir","#f-model","#f-domain","#f-cx","#f-sev","#f-acat","#f-dbl"].forEach(s=>$(s).addEventListener("change",render));
$("#f-text").addEventListener("input",render);
fillAcat();
$("#export").addEventListener("click",()=>{const out=DATA.map(r=>{const k=key(r);return{...r,...(ann[k]||{})}});
  const blob=new Blob([JSON.stringify(out.filter(r=>r.cat||r.note||r.dblcheck),null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="halluci_action_annotations.json";a.click();});
render();
</script></body></html>"""


def main():
    recs = build_records()
    out = HERE / "halluci_action_review.html"
    out.write_text(HTML.replace("__DATA__", json.dumps(recs, ensure_ascii=False)), encoding="utf-8")
    from collections import Counter
    print(f"records: {len(recs)}")
    print("by direction:", dict(Counter(r["direction"] for r in recs)))
    print("by severity :", dict(Counter(r["severity"] for r in recs)))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
