#!/usr/bin/env python3
"""Step 4 prep: stratified human-validation sample + self-contained review UI.

Sample: min(3, n) per A-track theme (C1/C2/C4-write open codes, seed=7) plus a
spot-check of the programmatic C4-read strata (4 silent-step, 3 reasoning-only,
3 narration-mismatch). The reviewer labels blind (coder-1 labels are embedded
only in the export payload, never displayed); Export downloads a JSON to score
agreement against open_codes_coder1.jsonl.
"""
import json, random, html
from pathlib import Path

HERE = Path(__file__).resolve().parent
cards = {c["card_id"]: c for c in map(json.loads, (HERE / "evidence_cards.jsonl").read_text().splitlines())}
codes = [json.loads(l) for l in (HERE / "open_codes_coder1.jsonl").read_text().splitlines()]
strata = [json.loads(l) for l in (HERE / "c4_read_assignments.jsonl").read_text().splitlines()]

rng = random.Random(7)
sample = []

themes_by_gate = {}
for r in codes:
    themes_by_gate.setdefault(r["gate"], set()).add(r["theme"])
for gate in ["C1", "C2", "C4"]:
    for theme in sorted(themes_by_gate.get(gate, [])):
        pool = [r for r in codes if r["gate"] == gate and r["theme"] == theme]
        for r in rng.sample(pool, min(3, len(pool))):
            sample.append({"card_id": r["card_id"], "kind": "theme", "gate": gate,
                           "coder1": r["theme"],
                           "options": sorted(themes_by_gate[gate]) + ["other"]})
read_opts = ["silent-step", "reasoning-only", "narration-mismatch", "other"]
for stratum, k in [("silent-step", 4), ("reasoning-only", 3), ("narration-mismatch", 3)]:
    pool = [a for a in strata if a["stratum"] == stratum]
    for a in rng.sample(pool, min(k, len(pool))):
        sample.append({"card_id": a["card_id"], "kind": "stratum", "gate": "C4-read",
                       "coder1": a["stratum"], "options": read_opts})

items = []
for s in sample:
    c = cards[s["card_id"]]
    items.append({**s,
                  "category": c["category"], "verbatim": c["verbatim"],
                  "context": [f"{x['sid']}: {x['text']}" for x in (c.get("context") or [])[:6]],
                  "trace": [f"s{t.get('step')}: {t.get('tool')}({t.get('params')})"
                            + (f" -> {t['result']}" if t.get("result") else "")
                            for t in (c.get("trace_evidence") or [])[:5]],
                  "judge_reason": c.get("judge_reason")})
rng.shuffle(items)

payload = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
page = """<!doctype html><meta charset="utf-8"><title>Thematic validation (n=%d)</title>
<style>
 body{font:14px/1.5 -apple-system,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#222}
 .item{border:1px solid #ddd;border-radius:8px;padding:12px 16px;margin:14px 0}
 .say{font-weight:600;background:#fff8e1;padding:6px 8px;border-radius:6px;margin:6px 0}
 .ctx,.tr{color:#555;font-size:13px;margin:2px 0 2px 12px}
 .tr{font-family:ui-monospace,monospace;font-size:12px;color:#265}
 .why{font-size:13px;color:#833;margin:6px 0}
 select,textarea{margin-top:6px;width:100%%}
 .tag{display:inline-block;background:#eef;border-radius:4px;padding:1px 6px;font-size:12px;margin-right:6px}
 #bar{position:sticky;top:0;background:#fff;padding:8px 0;border-bottom:1px solid #eee}
 button{padding:6px 14px}
</style>
<div id="bar"><b>Halluci-action thematic validation</b> — label each item with the best-fitting
theme (or <i>other</i>); coder-1 labels are hidden. <button onclick="exp()">Export JSON</button>
<span id="done"></span></div><div id="list"></div>
<script>
const ITEMS=%s;const KEY='thematic_validation_v1';
const saved=JSON.parse(localStorage.getItem(KEY)||'{}');
const list=document.getElementById('list');
ITEMS.forEach((it,i)=>{
 const d=document.createElement('div');d.className='item';
 d.innerHTML=`<span class="tag">${it.gate}</span><span class="tag">${it.category}</span>#${i+1} <code>${esc(it.card_id)}</code>
  <div class="say">${esc(it.verbatim)}</div>`
  +it.context.map(c=>`<div class="ctx">${esc(c)}</div>`).join('')
  +it.trace.map(t=>`<div class="tr">${esc(t)}</div>`).join('')
  +`<div class="why">judge: ${esc(it.judge_reason||'')}</div>
  <select id="s${i}"><option value="">— pick a label —</option>
   ${it.options.map(o=>`<option ${saved[it.card_id]?.label===o?'selected':''}>${o}</option>`).join('')}</select>
  <textarea id="n${i}" rows="1" placeholder="notes (optional)">${esc(saved[it.card_id]?.notes||'')}</textarea>`;
 list.appendChild(d);
 d.querySelector('select').onchange=d.querySelector('textarea').oninput=()=>{
  saved[it.card_id]={label:d.querySelector('select').value,notes:d.querySelector('textarea').value};
  localStorage.setItem(KEY,JSON.stringify(saved));prog();};
});
function esc(s){return (s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function prog(){const n=ITEMS.filter(it=>saved[it.card_id]?.label).length;
 document.getElementById('done').textContent=` ${n}/${ITEMS.length} labeled`}
function exp(){const out=ITEMS.map(it=>({card_id:it.card_id,gate:it.gate,kind:it.kind,
  coder1:it.coder1,human:saved[it.card_id]?.label||null,notes:saved[it.card_id]?.notes||''}));
 const a=document.createElement('a');
 a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));
 a.download='thematic_validation_export.json';a.click();}
prog();
</script>""" % (len(items), payload)

out = HERE / "validation_ui.html"
out.write_text(page)
print(f"wrote {out} with {len(items)} items "
      f"({sum(1 for i in items if i['kind']=='theme')} theme + {sum(1 for i in items if i['kind']=='stratum')} strata)")
