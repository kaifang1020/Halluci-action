from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "outputs"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Action Annotation Pilot</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; background: #f6f7f9; color: #20242a; font-size: 13px; }
#app { display: grid; grid-template-columns: 310px 1fr; height: 100vh; }
#sidebar { background: #20242a; color: #eef1f5; overflow: hidden; display: flex; flex-direction: column; }
#side-head { padding: 14px; border-bottom: 1px solid #3a4048; }
#side-head h1 { margin: 0 0 6px; font-size: 15px; }
#summary { color: #aeb7c2; font-size: 12px; }
#filters { padding: 10px 14px; border-bottom: 1px solid #3a4048; display: grid; gap: 7px; }
#filters label { display: flex; gap: 7px; align-items: center; color: #cfd6df; }
#items { overflow-y: auto; flex: 1; }
.nav-item { padding: 9px 12px; border-bottom: 1px solid #303640; cursor: pointer; display: grid; gap: 4px; }
.nav-item:hover { background: #303640; }
.nav-item.active { background: #3e4855; }
.nav-item.done .nav-title:after { content: " saved"; color: #9ee493; font-size: 10px; margin-left: 5px; }
.nav-title { font-weight: 700; font-size: 12px; }
.nav-meta { color: #aeb7c2; font-size: 11px; display: flex; justify-content: space-between; gap: 8px; }
.pill { border-radius: 999px; padding: 2px 7px; font-weight: 700; font-size: 10px; display: inline-block; }
.mut { background: #ffe4b5; color: #7a4a00; }
.read { background: #dcecff; color: #174f87; }

#main { overflow: auto; }
#top { position: sticky; top: 0; z-index: 5; background: white; border-bottom: 1px solid #dfe3e8; padding: 12px 18px; display: flex; align-items: center; gap: 10px; }
button { border: 1px solid #c8d0d8; background: #fff; border-radius: 6px; padding: 7px 10px; cursor: pointer; font-weight: 650; }
button:hover { background: #f0f3f6; }
button.primary { background: #2563eb; color: white; border-color: #2563eb; }
button.primary:hover { background: #1d4ed8; }
#title { font-size: 16px; font-weight: 750; flex: 1; }
#content { max-width: 1120px; padding: 18px; }
.band { background: white; border: 1px solid #dfe3e8; border-radius: 8px; margin-bottom: 14px; overflow: hidden; }
.band h2 { margin: 0; padding: 10px 12px; background: #f3f5f7; border-bottom: 1px solid #dfe3e8; font-size: 13px; }
.band-body { padding: 12px; }
.kv { display: grid; grid-template-columns: 130px 1fr; gap: 7px 12px; }
.key { color: #687381; font-weight: 700; }
pre { margin: 0; white-space: pre-wrap; word-break: break-word; background: #f8fafc; border: 1px solid #e3e8ef; border-radius: 6px; padding: 9px; max-height: 260px; overflow: auto; }
.sentence { border: 1px solid #dbe2ea; border-radius: 6px; padding: 8px 10px; margin-bottom: 7px; cursor: pointer; background: #fff; display: grid; grid-template-columns: 92px 1fr; gap: 8px; }
.sentence:hover { border-color: #93b4e8; }
.sentence.selected { background: #eaf2ff; border-color: #2563eb; }
.sid { color: #5b6673; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.sent-text { line-height: 1.42; }
.claim { border-left: 3px solid #9ab; padding: 6px 8px; background: #f8fafc; margin-bottom: 6px; }
.claim-type { font-size: 10px; font-weight: 800; color: #526170; }
.controls { display: grid; gap: 12px; }
.selected-summary { border: 1px solid #dbe2ea; border-radius: 6px; overflow: hidden; }
.selected-row { display: grid; grid-template-columns: 100px 120px 1fr; gap: 8px; padding: 8px 10px; border-top: 1px solid #edf1f5; align-items: start; }
.selected-row:first-child { border-top: 0; }
.selected-row .rel { font-weight: 800; color: #174f87; }
.selected-row .matched-claim { color: #526170; font-size: 12px; margin-top: 4px; }
.seg { display: flex; flex-wrap: wrap; gap: 7px; }
.seg button { font-weight: 700; }
.seg button.selected { background: #20242a; color: white; border-color: #20242a; }
textarea { width: 100%; min-height: 68px; border: 1px solid #ccd5df; border-radius: 6px; padding: 8px; font: inherit; }
.judge { display: none; }
.judge.open { display: block; }
#export-box { width: 100%; min-height: 180px; display: none; margin-top: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.empty { color: #8792a0; padding: 40px; text-align: center; }
</style>
</head>
<body>
<div id="app">
  <aside id="sidebar">
    <div id="side-head">
      <h1>Action Annotation Pilot</h1>
      <div id="summary"></div>
    </div>
    <div id="filters">
      <label><input type="checkbox" id="only-unsaved"> only unsaved</label>
      <label><input type="checkbox" id="only-mutation"> only mutation</label>
    </div>
    <div id="items"></div>
  </aside>
  <main id="main">
    <div id="top">
      <button onclick="prevItem()">Prev</button>
      <button onclick="nextItem()">Next</button>
      <div id="title">Select an action</div>
      <button onclick="toggleJudge()">Judge</button>
      <button class="primary" onclick="saveCurrent()">Save</button>
      <button onclick="exportJsonl()">Export JSONL</button>
    </div>
    <div id="content"><div class="empty">Pick an action on the left.</div></div>
  </main>
</div>

<script>
const ITEMS = __ITEMS__;
const PREDS = __PREDS__;
let current = 0;
let selectedSentences = new Set();
let relation = 'none';
let reqStatus = '';
let comments = '';
let showJudge = false;
const LS_KEY = 'stage3_action_annotation_pilot5_v1';
let annotations = JSON.parse(localStorage.getItem(LS_KEY) || '{}');

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function j(x) { return JSON.stringify(x ?? null, null, 2); }
function predFor(item) { return PREDS[item.item_id] || null; }
function savedFor(item) { return annotations[item.item_id] || null; }
function isSaved(item) { return Boolean(savedFor(item)); }
function sentenceById(item, id) {
  return (item.assistant_sentences || []).find(s => s.sentence_id === id) || null;
}
function relationForSentence(item, id) {
  const s = sentenceById(item, id);
  if (!s) return 'none';
  if (s.step_id < item.step_id) return 'pre_declared';
  if (s.step_id === item.step_id) return 'same_step';
  return 'post_reported';
}
function strongestRelation(relations) {
  const order = ['pre_declared', 'same_step', 'post_reported'];
  for (const r of order) if (relations.includes(r)) return r;
  return 'none';
}
function finalCell(said, reqStatus) {
  const r = (reqStatus === 'required' || reqStatus === 'allowed_supporting') ? 1 : 0;
  if (said && r === 1) return 'perfect';
  if (!said && r === 1) return 'silent_execution';
  if (said && r === 0) return 'unauthorized_declared';
  return 'unauthorized_silent';
}
function stage1ClaimsForSentence(item, sentence) {
  if (!sentence) return [];
  const groups = item.stage1_claims_window || [];
  const group = groups.find(g => g.step_id === sentence.step_id);
  if (!group) return [];
  const text = sentence.text || '';
  return (group.claims || [])
    .filter(c => c.span && text.includes(c.span))
    .map(c => ({
      step_id: sentence.step_id,
      claim_span: c.span,
      claim_type: c.type,
      requires_validation: c.requires_validation,
      validation_scope: c.validation_scope
    }));
}

function buildSidebar() {
  const onlyUnsaved = document.getElementById('only-unsaved').checked;
  const onlyMutation = document.getElementById('only-mutation').checked;
  const done = ITEMS.filter(isSaved).length;
  document.getElementById('summary').textContent = `${ITEMS.length} actions · ${done} saved`;
  document.getElementById('items').innerHTML = ITEMS.map((it, idx) => {
    if (onlyUnsaved && isSaved(it)) return '';
    if (onlyMutation && !it.is_mutation) return '';
    return `<div class="nav-item ${idx===current?'active':''} ${isSaved(it)?'done':''}" onclick="selectItem(${idx})">
      <div class="nav-title">${esc(it.traj_key)} · step ${it.step_id}</div>
      <div class="nav-meta"><span>${esc(it.tool_name)}</span><span class="pill ${it.is_mutation?'mut':'read'}">${it.is_mutation?'MUT':'READ'}</span></div>
    </div>`;
  }).join('');
}

function loadState() {
  const item = ITEMS[current];
  const a = savedFor(item) || {};
  selectedSentences = new Set(a.matched_sentence_ids || []);
  relation = a.relation_gold || (selectedSentences.size ? 'same_step' : 'none');
  reqStatus = a.requirement_status_gold || '';
  comments = a.comment || '';
}

function selectItem(idx) {
  current = idx;
  loadState();
  render();
}
function prevItem() { if (current > 0) selectItem(current - 1); }
function nextItem() { if (current < ITEMS.length - 1) selectItem(current + 1); }

function toggleSentence(id) {
  if (selectedSentences.has(id)) selectedSentences.delete(id);
  else selectedSentences.add(id);
  const item = ITEMS[current];
  relation = strongestRelation(Array.from(selectedSentences).map(id => relationForSentence(item, id)));
  render();
}
function setRelation(v) { relation = v; if (v === 'none') selectedSentences.clear(); render(); }
function setReq(v) { reqStatus = v; render(); }
function toggleJudge() { showJudge = !showJudge; render(); }

function renderSeg(name, values, selected, setter) {
  return `<div class="seg">${values.map(v => `<button class="${selected===v?'selected':''}" onclick="${setter}('${v}')">${v}</button>`).join('')}</div>`;
}

function render() {
  buildSidebar();
  const it = ITEMS[current];
  const p = predFor(it);
  const autoRelationNow = strongestRelation(Array.from(selectedSentences).map(id => relationForSentence(it, id)));
  relation = autoRelationNow;
  const selectedRows = Array.from(selectedSentences).map(id => {
    const s = sentenceById(it, id);
    const claims = stage1ClaimsForSentence(it, s);
    return { id, sentence: s, relation: relationForSentence(it, id), claims };
  });
  const selectedSummary = selectedRows.length ? `
    <div class="selected-summary">
      ${selectedRows.map(r => `<div class="selected-row">
        <div class="sid">${esc(r.id)}<br>step ${esc(r.sentence?.step_id ?? '')}</div>
        <div class="rel">${esc(r.relation)}</div>
        <div>
          ${esc(r.sentence?.text || '')}
          ${r.claims.length ? r.claims.map(c => `<div class="matched-claim">claim: <b>${esc(c.claim_type)}</b> · ${esc(c.claim_span)}</div>`).join('') : '<div class="matched-claim">claim: no exact stage1 span match</div>'}
        </div>
      </div>`).join('')}
    </div>` : '<div style="color:#8792a0">No sentence selected. This will export as said=false / relation=none.</div>';
  const cellNow = finalCell(selectedRows.length > 0, reqStatus);
  document.getElementById('title').textContent = `${it.traj_key} · ${it.action_id} · ${it.tool_name}`;
  const sentences = it.assistant_sentences.map(s => `
    <div class="sentence ${selectedSentences.has(s.sentence_id)?'selected':''}" onclick="toggleSentence('${s.sentence_id}')">
      <div class="sid">${esc(s.sentence_id)}<br>step ${s.step_id}<br>${selectedSentences.has(s.sentence_id) ? esc(relationForSentence(it, s.sentence_id)) : ''}</div>
      <div class="sent-text">${esc(s.text)}</div>
    </div>`).join('') || '<div class="empty">No assistant sentences in window.</div>';
  const claims = (it.stage1_claims_window || []).map(group => `
    <div><b>Step ${group.step_id}</b>${(group.claims || []).map(c => `
      <div class="claim"><div class="claim-type">${esc(c.type)} · requires=${esc(c.requires_validation)}</div>${esc(c.span)}</div>`).join('')}</div>`).join('') || '<span style="color:#8792a0">No stage1 claims loaded for this window.</span>';
  const judgeHtml = p ? `<div class="band judge ${showJudge?'open':''}">
    <h2>Judge Prediction</h2>
    <div class="band-body"><pre>${esc(j(p))}</pre></div>
  </div>` : `<div class="band judge ${showJudge?'open':''}"><h2>Judge Prediction</h2><div class="band-body">No prediction loaded yet.</div></div>`;

  document.getElementById('content').innerHTML = `
    <div class="band"><h2>Task</h2><div class="band-body kv">
      <div class="key">task_id</div><div>${esc(it.task_id)}</div>
      <div class="key">instruction</div><div>${esc(it.task)}</div>
      <div class="key">ground truth</div><pre>${esc(j(it.task_definition.ground_truth_steps))}</pre>
      <div class="key">constraints</div><pre>${esc(j(it.task_definition.system_constraints))}</pre>
    </div></div>
    <div class="band"><h2>Executed Action</h2><div class="band-body kv">
      <div class="key">item_id</div><div>${esc(it.item_id)}</div>
      <div class="key">tool</div><div>${esc(it.tool_name)} <span class="pill ${it.is_mutation?'mut':'read'}">${it.is_mutation?'MUTATION':'READ'}</span></div>
      <div class="key">parameters</div><pre>${esc(j(it.parameters))}</pre>
      <div class="key">tool result</div><pre>${esc(j(it.tool_result))}</pre>
      <div class="key">audit delta</div><pre>${esc(j(it.audit_delta))}</pre>
    </div></div>
    <div class="band"><h2>Assistant Sentences: select matching sentence(s)</h2><div class="band-body">${sentences}</div></div>
    <div class="band"><h2>Your Labels</h2><div class="band-body controls">
      <div><b>Overall Relation</b> <span class="pill read">${esc(autoRelationNow)}</span> <span style="color:#687381">auto from selected sentence steps; per-sentence relations are exported</span></div>
      <div><b>Requirement Status</b>${renderSeg('req', ['required','allowed_supporting','unnecessary','forbidden'], reqStatus, 'setReq')}</div>
      <div><b>Final Cell</b> <span class="pill ${cellNow.includes('unauthorized')?'mut':'read'}">${esc(cellNow)}</span></div>
      <div><b>Selected Sentence Matches</b>${selectedSummary}</div>
      <label><b>Comment</b><textarea id="comment" oninput="comments=this.value">${esc(comments)}</textarea></label>
    </div></div>
    <div class="band"><h2>Stage1 Claims Window</h2><div class="band-body">${claims}</div></div>
    ${judgeHtml}
    <textarea id="export-box" readonly></textarea>
  `;
}

function currentAnnotation() {
  const it = ITEMS[current];
  const ids = Array.from(selectedSentences);
  const said = ids.length > 0;
  const matched_sentence_relations = ids.map(id => {
    const s = sentenceById(it, id);
    const rel = relationForSentence(it, id);
    return {
      sentence_id: id,
      step_id: s ? s.step_id : null,
      relation: rel,
      text: s ? s.text : ''
    };
  });
  const matched_claims = matched_sentence_relations.flatMap(ms => {
    const s = sentenceById(it, ms.sentence_id);
    return stage1ClaimsForSentence(it, s).map(c => ({ ...c, sentence_id: ms.sentence_id, relation: ms.relation }));
  });
  const autoRelation = strongestRelation(matched_sentence_relations.map(ms => ms.relation));
  return {
    item_id: it.item_id,
    traj_key: it.traj_key,
    action_id: it.action_id,
    tool_name: it.tool_name,
    matched_sentence_ids: ids,
    matched_sentence_relations,
    matched_claims,
    said_gold: said,
    relation_gold: said ? autoRelation : 'none',
    requirement_status_gold: reqStatus,
    R_gold: (reqStatus === 'required' || reqStatus === 'allowed_supporting') ? 1 : 0,
    comment: comments
  };
}
function saveCurrent() {
  const a = currentAnnotation();
  if (!a.requirement_status_gold) {
    alert('Please choose requirement_status first.');
    return;
  }
  annotations[a.item_id] = a;
  localStorage.setItem(LS_KEY, JSON.stringify(annotations));
  buildSidebar();
}
function exportJsonl() {
  const lines = ITEMS.filter(it => annotations[it.item_id]).map(it => JSON.stringify(annotations[it.item_id]));
  const text = lines.join('\n') + (lines.length ? '\n' : '');
  const box = document.getElementById('export-box');
  box.style.display = 'block';
  box.value = text;
  box.focus();
  box.select();
  navigator.clipboard?.writeText(text);
}
document.getElementById('only-unsaved').addEventListener('change', buildSidebar);
document.getElementById('only-mutation').addEventListener('change', buildSidebar);
loadState();
render();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=Path, default=OUT_DIR / "pilot_5_action_items.jsonl")
    parser.add_argument("--predictions", type=Path, default=OUT_DIR / "pilot_5_judge_predictions.jsonl")
    parser.add_argument("--out", type=Path, default=HERE / "annotation_ui.html")
    args = parser.parse_args()

    items = read_jsonl(args.items)
    preds = {row["item_id"]: row for row in read_jsonl(args.predictions)}
    html = HTML.replace("__ITEMS__", json.dumps(items, ensure_ascii=False))
    html = html.replace("__PREDS__", json.dumps(preds, ensure_ascii=False))
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote UI for {len(items)} actions -> {args.out}")
    if preds:
        print(f"Loaded {len(preds)} judge predictions")


if __name__ == "__main__":
    main()
