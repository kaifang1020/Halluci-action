"""
Generate a self-contained HTML review UI for Stage 2 annotations.

Usage:
    python research/annotations/v2/stage2/generate_review_ui.py

Output:
    research/annotations/v2/stage2/review_ui.html
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Script is at: research/annotations/v2/stage2/generate_review_ui.py
# parent chain: stage2/ → v2/ → annotations/ → research/
STAGE2_DIR  = Path(__file__).resolve().parent            # research/annotations/v2/stage2/
STAGE1_DIR  = STAGE2_DIR.parent                          # research/annotations/v2/
RESEARCH    = STAGE1_DIR.parent.parent                   # research/
TRAJS_ROOT  = RESEARCH / "experiments_v2/real/independent"

TRAJ_PATHS = {
    "C-1_deepseek":    TRAJS_ROOT / "crm/trajectories/C-1_deepseek_deepseek_chat.json",
    "C-5_deepseek":    TRAJS_ROOT / "crm/trajectories/C-5_deepseek_deepseek_chat.json",
    "D-5_deepseek_r02": TRAJS_ROOT / "helpdesk/trajectories/D-5_deepseek_deepseek_chat_r02.json",
    "H-2_deepseek":    TRAJS_ROOT / "hr/trajectories/H-2_deepseek_deepseek_chat.json",
    "PR-2_deepseek":   TRAJS_ROOT / "project/trajectories/PR-2_deepseek_deepseek_chat.json",
}


def parse_stage1(path: Path) -> dict[str, dict]:
    text = path.read_text()
    claims: dict[str, dict] = {}
    blocks = re.split(r"^#### ", text, flags=re.MULTILINE)
    for block in blocks[1:]:
        cid_m = re.match(r"(\S+)", block)
        if not cid_m:
            continue
        cid = cid_m.group(1)
        span_m = re.search(r"^Span:\s*`?(.+?)`?\s*$", block, re.MULTILINE)
        type_m = re.search(r"^Type:\s*(\S+)", block, re.MULTILINE)
        req_m  = re.search(r"^Requires validation:\s*(\S+)", block, re.MULTILINE)
        # Extract step_id from claim id pattern e.g. C1-S3-C1 → 3
        step_m = re.search(r"-S(\d+)-", cid)
        claims[cid] = {
            "span": span_m.group(1).strip() if span_m else "",
            "type": type_m.group(1).strip() if type_m else "",
            "requires_validation": req_m.group(1).strip() == "yes" if req_m else False,
            "step_id": int(step_m.group(1)) if step_m else 0,
        }
    return claims


def parse_stage2(path: Path) -> dict[str, dict]:
    text = path.read_text()
    claims: dict[str, dict] = {}
    blocks = re.split(r"^### ", text, flags=re.MULTILINE)
    for block in blocks[1:]:
        cid_m = re.match(r"(\S+)", block)
        if not cid_m:
            continue
        cid = cid_m.group(1)
        verdict_m = re.search(r"^Verdict:\s*(\S+)", block, re.MULTILINE)
        channel_m = re.search(r"- channel:\s*`?(.+?)`?\s*$", block, re.MULTILINE)
        step_m    = re.search(r"- step:\s*(\S+)", block, re.MULTILINE)
        ref_m     = re.search(r"- ref:\s*(.+)", block, re.MULTILINE)
        reason_m  = re.search(r"^Reason:\s*(.+)", block, re.MULTILINE)
        notes_m   = re.search(r"^Notes:\s*(.+)", block, re.MULTILINE)
        claims[cid] = {
            "verdict":  verdict_m.group(1)         if verdict_m else "?",
            "channel":  channel_m.group(1).strip() if channel_m else "",
            "ev_step":  step_m.group(1).strip()    if step_m   else "",
            "ref":      ref_m.group(1).strip()     if ref_m    else "",
            "reason":   reason_m.group(1).strip()  if reason_m else "",
            "notes":    notes_m.group(1).strip()   if notes_m  else "",
        }
    return claims


def load_traj(path: Path) -> dict:
    raw = json.loads(path.read_text())
    steps = []
    for s in raw.get("steps", []):
        steps.append({
            "step_id":       s.get("step_id", 0),
            "assistant_text": s.get("assistant_text") or "",
            "tool_calls":    s.get("tool_calls") or [],
            "tool_results":  s.get("tool_results") or [],
        })
    return {
        "task_id": raw.get("task_id", ""),
        "task":    raw.get("task", ""),
        "model":   raw.get("model", ""),
        "steps":   steps,
    }


def build_payload() -> list[dict]:
    payload = []
    for traj_id, traj_path in TRAJ_PATHS.items():
        s1 = parse_stage1(STAGE1_DIR / f"{traj_id}.md")
        s2 = parse_stage2(STAGE2_DIR / f"{traj_id}.md")
        traj = load_traj(traj_path)

        # Build per-step claim list
        step_claims: dict[int, list] = {}
        for cid, info in s2.items():
            s1info = s1.get(cid, {})
            step_id = s1info.get("step_id", 0)
            step_claims.setdefault(step_id, []).append({
                "claim_id": cid,
                "span":     s1info.get("span", ""),
                "type":     s1info.get("type", ""),
                "verdict":  info["verdict"],
                "channel":  info["channel"],
                "ev_step":  info["ev_step"],
                "ref":      info["ref"],
                "reason":   info["reason"],
                "notes":    info["notes"],
            })

        # Sort claims within each step by claim id
        for step_id in step_claims:
            step_claims[step_id].sort(key=lambda x: x["claim_id"])

        payload.append({
            "traj_id":     traj_id,
            "task_id":     traj["task_id"],
            "task":        traj["task"],
            "model":       traj["model"],
            "steps":       traj["steps"],
            "step_claims": {str(k): v for k, v in step_claims.items()},
        })
    return payload


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Stage 2 Annotation Review</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 14px; background: #f0f2f5; color: #222; }

/* Layout */
#app { display: flex; flex-direction: column; height: 100vh; }
#topbar { background: #1a1a2e; color: #eee; padding: 10px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
#topbar h1 { font-size: 16px; font-weight: 600; color: #a0c4ff; }
#topbar select { padding: 4px 8px; border-radius: 4px; border: none; font-size: 14px; }
#progress-bar { flex: 1; background: #333; border-radius: 8px; height: 8px; overflow: hidden; }
#progress-fill { height: 100%; background: #4ade80; transition: width 0.3s; }
#progress-text { font-size: 12px; color: #aaa; white-space: nowrap; }
#export-btn { background: #4ade80; color: #000; border: none; border-radius: 4px; padding: 5px 12px; cursor: pointer; font-weight: 600; font-size: 13px; }
#export-btn:hover { background: #22c55e; }

#main { display: flex; flex: 1; overflow: hidden; }

/* Left: trajectory panel */
#left-panel { width: 44%; min-width: 340px; display: flex; flex-direction: column; border-right: 1px solid #d0d5dd; background: #fff; }
#step-nav { padding: 10px 12px; border-bottom: 1px solid #e5e9f0; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
#step-nav span { font-size: 12px; color: #666; margin-right: 4px; }
.step-btn { padding: 4px 10px; border: 1px solid #d0d5dd; border-radius: 4px; cursor: pointer; font-size: 13px; background: #f8f9fa; transition: all 0.15s; }
.step-btn:hover { background: #e9ecef; }
.step-btn.active { background: #1a1a2e; color: #fff; border-color: #1a1a2e; }
.step-btn.has-claims { border-color: #6366f1; }
.step-btn.has-issues { border-color: #ef4444; background: #fef2f2; }

#traj-content { flex: 1; overflow-y: auto; padding: 14px; }
.traj-meta { background: #f8f9fa; border-radius: 6px; padding: 10px 12px; margin-bottom: 12px; font-size: 12px; color: #555; }
.traj-meta strong { color: #1a1a2e; }

.step-section { margin-bottom: 20px; }
.step-header { font-weight: 700; font-size: 13px; color: #1a1a2e; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 2px solid #e9ecef; }
.assistant-text { background: #f8faff; border-left: 3px solid #6366f1; padding: 10px 12px; border-radius: 0 6px 6px 0; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; margin-bottom: 8px; }

.tool-block { margin: 6px 0; border-radius: 6px; overflow: hidden; border: 1px solid #e5e9f0; }
.tool-header { padding: 5px 10px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none; }
.tool-call-header { background: #eff6ff; color: #1e40af; }
.tool-result-header { background: #f0fdf4; color: #166534; }
.tool-body { padding: 8px 10px; font-family: "SF Mono", "Fira Code", monospace; font-size: 11.5px; background: #fafafa; white-space: pre-wrap; word-break: break-all; max-height: 260px; overflow-y: auto; display: none; }
.tool-block.open .tool-body { display: block; }

/* Right: annotation panel */
#right-panel { flex: 1; overflow-y: auto; padding: 14px; background: #f8f9fa; }
#right-panel h2 { font-size: 13px; font-weight: 700; color: #555; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.05em; }

.claim-card { background: #fff; border: 1px solid #e5e9f0; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; transition: border-color 0.2s; }
.claim-card.verdict-not_supported { border-left: 4px solid #ef4444; }
.claim-card.verdict-supported     { border-left: 4px solid #22c55e; }
.claim-card.verdict-unverifiable  { border-left: 4px solid #f59e0b; }
.claim-card.reviewed-ok   { background: #f0fdf4; }
.claim-card.reviewed-fix  { background: #fff7ed; }
.claim-card.reviewed-q    { background: #fefce8; }

.claim-header { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 8px; }
.claim-id { font-size: 11px; font-weight: 700; color: #6366f1; white-space: nowrap; }
.claim-type-badge { font-size: 11px; padding: 1px 7px; border-radius: 10px; background: #e9ecef; color: #444; white-space: nowrap; }
.verdict-badge { font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 4px; white-space: nowrap; }
.verdict-supported     { background: #dcfce7; color: #166534; }
.verdict-not_supported { background: #fee2e2; color: #991b1b; }
.verdict-unverifiable  { background: #fef9c3; color: #854d0e; }

.claim-span { font-size: 13px; color: #222; background: #f8f9fa; border-radius: 4px; padding: 5px 8px; margin-bottom: 8px; font-style: italic; line-height: 1.5; }

.evidence-grid { display: grid; grid-template-columns: 70px 1fr; gap: 3px 8px; font-size: 12px; margin-bottom: 8px; }
.ev-label { color: #888; font-weight: 600; text-align: right; }
.ev-val { color: #333; word-break: break-word; font-family: "SF Mono", monospace; font-size: 11.5px; }
.reason-text { font-size: 12px; color: #555; background: #f8f9fa; padding: 5px 8px; border-radius: 4px; margin-bottom: 8px; line-height: 1.5; }
.notes-text { font-size: 11px; color: #888; font-style: italic; }

.review-controls { display: flex; gap: 6px; align-items: center; margin-top: 10px; padding-top: 8px; border-top: 1px solid #f0f0f0; }
.review-controls label { font-size: 12px; color: #666; font-weight: 600; }
.review-btn { padding: 4px 12px; border: 1px solid #d0d5dd; border-radius: 4px; cursor: pointer; font-size: 12px; background: #f8f9fa; transition: all 0.15s; }
.review-btn:hover { background: #e9ecef; }
.review-btn.active-ok  { background: #22c55e; color: #fff; border-color: #22c55e; }
.review-btn.active-fix { background: #f97316; color: #fff; border-color: #f97316; }
.review-btn.active-q   { background: #eab308; color: #fff; border-color: #eab308; }
.ha-type-sel { font-size: 12px; padding: 3px 6px; border: 1px solid #d0d5dd; border-radius: 4px; }
.comment-input { flex: 1; font-size: 12px; padding: 3px 8px; border: 1px solid #d0d5dd; border-radius: 4px; }

.no-claims { color: #aaa; font-size: 13px; font-style: italic; padding: 20px 0; text-align: center; }
</style>
</head>
<body>
<div id="app">
  <div id="topbar">
    <h1>Stage 2 Annotation Review</h1>
    <select id="traj-select"></select>
    <div id="progress-bar"><div id="progress-fill" style="width:0%"></div></div>
    <span id="progress-text">0 / 0 reviewed</span>
    <button id="export-btn" onclick="exportReview()">⬇ Export JSON</button>
  </div>
  <div id="main">
    <div id="left-panel">
      <div id="step-nav"><span>Steps:</span></div>
      <div id="traj-content"></div>
    </div>
    <div id="right-panel">
      <h2>Claims for selected step</h2>
      <div id="claims-container"></div>
    </div>
  </div>
</div>

<script>
const DATA = __DATA_PLACEHOLDER__;

// Review state: { traj_id: { claim_id: { status, ha_type, comment } } }
const reviewState = {};

let currentTrajIdx = 0;
let currentStepId  = null;

// ── Init ──────────────────────────────────────────────────────────────────────
function init() {
  const sel = document.getElementById('traj-select');
  DATA.forEach((t, i) => {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = `${t.traj_id}  (${t.task_id}: ${t.task.slice(0, 50)}…)`;
    sel.appendChild(opt);
    reviewState[t.traj_id] = {};
  });
  sel.addEventListener('change', () => { currentTrajIdx = +sel.value; renderTraj(); });
  renderTraj();
}

// ── Render trajectory ─────────────────────────────────────────────────────────
function renderTraj() {
  const t = DATA[currentTrajIdx];
  if (!t) return;

  // Step nav
  const nav = document.getElementById('step-nav');
  nav.innerHTML = '<span>Steps:</span>';
  t.steps.forEach(s => {
    const hasClaims = (t.step_claims[s.step_id] || []).length > 0;
    const hasIssues = hasClaims && (t.step_claims[s.step_id] || []).some(c => c.verdict === 'not_supported');
    const btn = document.createElement('button');
    btn.className = 'step-btn' + (hasClaims ? ' has-claims' : '') + (hasIssues ? ' has-issues' : '');
    btn.textContent = s.step_id;
    btn.onclick = () => selectStep(s.step_id);
    nav.appendChild(btn);
  });

  // Meta
  const content = document.getElementById('traj-content');
  content.innerHTML = `
    <div class="traj-meta">
      <strong>${t.task_id}</strong> &nbsp;|&nbsp; ${escHtml(t.task)}<br>
      <span>Model: ${t.model}</span>
    </div>
  `;

  // Render all steps
  t.steps.forEach(s => {
    const sec = document.createElement('div');
    sec.className = 'step-section';
    sec.id = `step-sec-${s.step_id}`;
    let html = `<div class="step-header">Step ${s.step_id}</div>`;
    if (s.assistant_text) {
      html += `<div class="assistant-text">${escHtml(s.assistant_text)}</div>`;
    }
    // Tool calls + results interleaved by call_id
    s.tool_calls.forEach(tc => {
      const tr = s.tool_results.find(r => r.call_id === tc.call_id);
      html += toolCallHtml(tc);
      if (tr) html += toolResultHtml(tr);
    });
    sec.innerHTML = html;
    content.appendChild(sec);
  });

  // Select first step that has claims, else first step
  const firstWithClaims = t.steps.find(s => (t.step_claims[s.step_id] || []).length > 0);
  selectStep(firstWithClaims ? firstWithClaims.step_id : t.steps[0]?.step_id);
  updateProgress();
}

function toolCallHtml(tc) {
  return `<div class="tool-block" onclick="toggleBlock(this)">
    <div class="tool-header tool-call-header">
      <span>▶ ${escHtml(tc.tool_name)}(${shortParams(tc.parameters)})</span>
      <span style="font-size:11px;opacity:0.7">click to expand</span>
    </div>
    <pre class="tool-body">${escHtml(JSON.stringify(tc.parameters, null, 2))}</pre>
  </div>`;
}

function toolResultHtml(tr) {
  return `<div class="tool-block" onclick="toggleBlock(this)">
    <div class="tool-header tool-result-header">
      <span>◀ ${escHtml(tr.tool_name)} result</span>
      <span style="font-size:11px;opacity:0.7">click to expand</span>
    </div>
    <pre class="tool-body">${escHtml(JSON.stringify(tr.result, null, 2))}</pre>
  </div>`;
}

function toggleBlock(el) { el.classList.toggle('open'); }

function shortParams(p) {
  const s = JSON.stringify(p);
  return s.length > 60 ? s.slice(0, 57) + '…' : s;
}

// ── Select step ───────────────────────────────────────────────────────────────
function selectStep(stepId) {
  currentStepId = stepId;
  const t = DATA[currentTrajIdx];

  // Highlight nav button
  document.querySelectorAll('.step-btn').forEach(b => {
    b.classList.toggle('active', +b.textContent === stepId);
  });

  // Scroll step into view
  const sec = document.getElementById(`step-sec-${stepId}`);
  if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // Render claims
  const container = document.getElementById('claims-container');
  container.innerHTML = '';
  const claims = t.step_claims[stepId] || [];

  if (claims.length === 0) {
    container.innerHTML = '<div class="no-claims">No validated claims in this step</div>';
    return;
  }

  claims.forEach(c => {
    container.appendChild(claimCard(t.traj_id, c));
  });
}

// ── Claim card ────────────────────────────────────────────────────────────────
function claimCard(trajId, c) {
  const rv = reviewState[trajId][c.claim_id] || {};
  const div = document.createElement('div');
  div.id = `card-${c.claim_id}`;
  div.className = `claim-card verdict-${c.verdict}` +
    (rv.status ? ` reviewed-${rv.status}` : '');

  const verdictBadge = `<span class="verdict-badge verdict-${c.verdict}">${c.verdict === 'supported' ? '✓' : '❌'} ${c.verdict}</span>`;
  // Show HA type selector when a hallucination is confirmed:
  //   - not_supported + OK  → reviewer agrees it's a HA, wants to label the type
  //   - any verdict  + Fix  → reviewer is marking it as a HA
  const showHaType = (rv.status === 'ok' && c.verdict === 'not_supported') || rv.status === 'fix';
  const haTypeSel = showHaType ? `
    <select class="ha-type-sel" onchange="setHaType('${trajId}','${c.claim_id}',this.value)">
      <option value="">HA type…</option>
      <option value="fabrication"     ${rv.ha_type==='fabrication'     ?'selected':''}>Fabrication</option>
      <option value="substitution"    ${rv.ha_type==='substitution'    ?'selected':''}>Substitution</option>
      <option value="over-claim"      ${rv.ha_type==='over-claim'      ?'selected':''}>Over-claim</option>
      <option value="under-claim"     ${rv.ha_type==='under-claim'     ?'selected':''}>Under-claim</option>
      <option value="premature-claim" ${rv.ha_type==='premature-claim' ?'selected':''}>Premature Claim</option>
      <option value="constraint-viol" ${rv.ha_type==='constraint-viol' ?'selected':''}>Constraint Violation</option>
      <option value="abandoned-intent"${rv.ha_type==='abandoned-intent'?'selected':''}>Abandoned Intention</option>
      <option value="annotation-error"${rv.ha_type==='annotation-error'?'selected':''}>Annotation Error</option>
    </select>` : '';

  div.innerHTML = `
    <div class="claim-header">
      <span class="claim-id">${c.claim_id}</span>
      <span class="claim-type-badge">${c.type}</span>
      ${verdictBadge}
    </div>
    <div class="claim-span">"${escHtml(c.span)}"</div>
    <div class="evidence-grid">
      <span class="ev-label">Channel</span><span class="ev-val">${escHtml(c.channel)}</span>
      <span class="ev-label">Ev. step</span><span class="ev-val">${escHtml(c.ev_step)}</span>
      <span class="ev-label">Ref</span><span class="ev-val">${escHtml(c.ref)}</span>
    </div>
    <div class="reason-text"><strong>Reason:</strong> ${escHtml(c.reason)}</div>
    ${c.notes ? `<div class="notes-text">Notes: ${escHtml(c.notes)}</div>` : ''}
    <div class="review-controls">
      <label>Review:</label>
      <button class="review-btn ${rv.status==='ok'  ?'active-ok' :''}" onclick="setReview('${trajId}','${c.claim_id}','ok')">✓ OK</button>
      <button class="review-btn ${rv.status==='fix' ?'active-fix':''}" onclick="setReview('${trajId}','${c.claim_id}','fix')">⚠ Fix</button>
      <button class="review-btn ${rv.status==='q'   ?'active-q'  :''}" onclick="setReview('${trajId}','${c.claim_id}','q')">? Unsure</button>
      ${haTypeSel}
      <input class="comment-input" type="text" placeholder="Comment…"
        value="${escHtml(rv.comment||'')}"
        oninput="setComment('${trajId}','${c.claim_id}',this.value)">
    </div>`;
  return div;
}

// ── Review actions ─────────────────────────────────────────────────────────────
function setReview(trajId, claimId, status) {
  if (!reviewState[trajId][claimId]) reviewState[trajId][claimId] = {};
  reviewState[trajId][claimId].status = status;
  refreshCard(trajId, claimId);
  updateProgress();
}
function setHaType(trajId, claimId, val) {
  if (!reviewState[trajId][claimId]) reviewState[trajId][claimId] = {};
  reviewState[trajId][claimId].ha_type = val;
}
function setComment(trajId, claimId, val) {
  if (!reviewState[trajId][claimId]) reviewState[trajId][claimId] = {};
  reviewState[trajId][claimId].comment = val;
}
function refreshCard(trajId, claimId) {
  const t = DATA.find(x => x.traj_id === trajId);
  const c = Object.values(t.step_claims).flat().find(x => x.claim_id === claimId);
  const old = document.getElementById(`card-${claimId}`);
  if (old) old.replaceWith(claimCard(trajId, c));
}

// ── Progress ──────────────────────────────────────────────────────────────────
function updateProgress() {
  let total = 0, done = 0;
  DATA.forEach(t => {
    Object.values(t.step_claims).flat().forEach(c => {
      total++;
      if (reviewState[t.traj_id][c.claim_id]?.status) done++;
    });
  });
  document.getElementById('progress-fill').style.width = total ? (done/total*100)+'%' : '0%';
  document.getElementById('progress-text').textContent = `${done} / ${total} reviewed`;
}

// ── Export ────────────────────────────────────────────────────────────────────
function exportReview() {
  const out = {};
  DATA.forEach(t => {
    out[t.traj_id] = {};
    Object.values(t.step_claims).flat().forEach(c => {
      const rv = reviewState[t.traj_id][c.claim_id] || {};
      out[t.traj_id][c.claim_id] = {
        span:    c.span,
        type:    c.type,
        verdict: c.verdict,
        review:  rv.status || null,
        ha_type: rv.ha_type || null,
        comment: rv.comment || null,
      };
    });
  });
  const blob = new Blob([JSON.stringify(out, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'stage2_review_results.json';
  a.click();
}

function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

init();
</script>
</body>
</html>
"""


def main() -> None:
    payload = build_payload()
    data_json = json.dumps(payload, ensure_ascii=False, indent=None)
    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)
    out = STAGE2_DIR / "review_ui.html"
    out.write_text(html, encoding="utf-8")
    total_claims = sum(
        len(claims)
        for t in payload
        for claims in t["step_claims"].values()
    )
    print(f"Generated: {out}")
    print(f"Trajectories: {len(payload)}, Total validated claims: {total_claims}")


if __name__ == "__main__":
    main()
