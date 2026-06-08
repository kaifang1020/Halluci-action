"""
Generate a self-contained HTML review UI for binary Stage 2 results.

Shows every trajectory that contains at least one not_supported or
needs_broader_context verdict, with the full raw trajectory on the left
and the flagged claims on the right.

Defaults preserve the original deepseek_chat / experiments_v2/real flow.
For a different model run, pass CLI overrides:

  # original deepseek_chat:
  python -m research.eval_v3.stage2.generate_review_ui

  # deepseek_reasoner:
  python -m research.eval_v3.stage2.generate_review_ui \\
      --results-dir deepseek_reasoner \\
      --exp-root experiments_v2 \\
      --output-html deepseek_reasoner_review_ui.html \\
      --title-suffix "DeepSeek Reasoner"
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent          # .../research/eval_v3/stage2/
RESEARCH = SCRIPT_DIR.parent.parent                  # .../research/

FLAGGED_VERDICTS = {"not_supported", "needs_broader_context"}


# ── 1. Index trajectory_id → file path ────────────────────────────────────────

def _build_traj_index(exp_root: Path) -> dict[str, Path]:
    """Index trajectory_id → file, scanning only */trajectories/*.json to avoid audit files."""
    index: dict[str, Path] = {}
    for f in exp_root.rglob("*/trajectories/*.json"):
        try:
            d = json.loads(f.read_text())
            tid = d.get("trajectory_id")
            if tid:
                index[tid] = f
        except Exception:
            pass
    return index


# ── 2. Load all flagged claims grouped by (split, file_stem) ──────────────────

def _load_flagged(results_dir: Path, exp_root: Path) -> list[dict]:
    """Return list of trajectory dicts ready to embed in JS."""
    traj_index = _build_traj_index(exp_root)

    # Collect claims grouped by verdict file
    by_file: dict[tuple[str, str], list[dict]] = {}
    for split in ("independent", "dependent"):
        for vf in sorted((results_dir / split).glob("*.jsonl")):
            claims = []
            for line in vf.read_text().splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("verdict") in FLAGGED_VERDICTS:
                    claims.append(r)
            if claims:
                by_file[(split, vf.stem)] = claims

    # Build per-trajectory objects
    trajs = []
    for (split, stem), flagged_claims in sorted(by_file.items()):
        # Find trajectory JSON via traj_id (all claims share same traj_id)
        traj_id = flagged_claims[0]["traj_id"]
        traj_path = traj_index.get(traj_id)
        if traj_path is None:
            print(f"  WARNING: trajectory not found for {stem} (traj_id={traj_id})")
            continue

        traj_json = json.loads(traj_path.read_text())

        # Derive display label: strip provider suffix from stem
        label = re.sub(r"_gemini-pro_v1_verdicts$", "", stem)

        # Index flagged claims by step_id
        by_step: dict[int, list[dict]] = {}
        for c in flagged_claims:
            # claim_id: {traj_id}__S{step}-C{idx}
            m = re.search(r"__S(\d+)-C", c["claim_id"])
            step_num = int(m.group(1)) if m else c.get("step_id", 0)
            by_step.setdefault(step_num, []).append(c)

        # Index ALL steps by step_id for evidence extraction
        step_by_id: dict[int, dict] = {
            s["step_id"]: s for s in traj_json.get("steps", [])
        }

        def _extract_evidence_snippet(claim: dict) -> str | None:
            """Pull the raw tool call/result JSON from the evidence step."""
            ev = claim.get("evidence_pointer") or {}
            ev_step = ev.get("step")
            channel = ev.get("channel")
            if ev_step is None or channel not in ("tool_calls", "tool_results"):
                return None
            s = step_by_id.get(ev_step)
            if not s:
                return None
            items = s.get(channel, [])
            if not items:
                return None
            # Match by tool name first, then disambiguate by parameter values
            # appearing in the judge's ref text (e.g., "project_id=4")
            ref = ev.get("ref", "")
            ref_lower = ref.lower()
            candidates = [it for it in items if it.get("tool_name", "") and it["tool_name"] in ref]
            if not candidates:
                candidates = items
            # Score each candidate by how many of its parameter values appear in ref
            def _param_score(item):
                params = item.get("parameters", {}) or {}
                score = 0
                for k, v in params.items():
                    if v is None or isinstance(v, bool):
                        continue
                    vs = str(v).lower()
                    # Avoid trivial matches on very short strings
                    if len(vs) < 1:
                        continue
                    # Match patterns like "project_id=4" or "project_id: 4"
                    if f"{k.lower()}={vs}" in ref_lower or f"{k.lower()}: {vs}" in ref_lower:
                        score += 10
                    elif vs in ref_lower:
                        score += 1
                return score
            target = max(candidates, key=_param_score) if candidates else items[0]
            try:
                return json.dumps(target, ensure_ascii=False, indent=2)
            except Exception:
                return None

        # Build steps list, attaching evidence snippets to each flagged claim
        steps = []
        for step in traj_json.get("steps", []):
            sid = step["step_id"]
            flagged = by_step.get(sid, [])
            enriched = []
            for c in flagged:
                c2 = dict(c)
                c2["_evidence_snippet"] = _extract_evidence_snippet(c)
                enriched.append(c2)
            steps.append({
                "step_id": sid,
                "assistant_text": step.get("assistant_text", ""),
                "tool_calls": step.get("tool_calls", []),
                "tool_results": step.get("tool_results", []),
                "flagged_claims": enriched,
            })

        trajs.append({
            "split": split,
            "label": label,
            "traj_id": traj_id,
            "task_id": traj_json.get("task_id", ""),
            "task": traj_json.get("task", ""),
            "steps": steps,
            "total_flagged": len(flagged_claims),
            "not_supported_count": sum(1 for c in flagged_claims if c["verdict"] == "not_supported"),
            "needs_broader_context_count": sum(1 for c in flagged_claims if c["verdict"] == "needs_broader_context"),
        })

    return trajs


# ── 3. Render HTML ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>PAGE_TITLE</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; background: #f5f5f5; }

/* Layout */
#app { display: flex; height: 100vh; }
#sidebar { width: 260px; min-width: 200px; background: #1e1e2e; color: #cdd6f4; display: flex; flex-direction: column; overflow: hidden; }
#sidebar-header { padding: 12px 14px; background: #181825; font-weight: bold; font-size: 14px; border-bottom: 1px solid #313244; flex-shrink: 0; }
#traj-list { flex: 1; overflow-y: auto; }
.traj-item { padding: 9px 14px; cursor: pointer; border-bottom: 1px solid #313244; display: flex; justify-content: space-between; align-items: flex-start; }
.traj-item:hover { background: #313244; }
.traj-item.active { background: #45475a; }
.traj-label { font-size: 12px; font-weight: 600; }
.traj-split { font-size: 10px; color: #6c7086; margin-top: 2px; }
.traj-counts { display: flex; gap: 4px; flex-shrink: 0; align-items: center; margin-top: 1px; }
.badge { font-size: 10px; padding: 1px 5px; border-radius: 9px; font-weight: bold; }
.badge-ns { background: #f38ba8; color: #1e1e2e; }
.badge-nbc { background: #fab387; color: #1e1e2e; }

/* Main area */
#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#top-bar { background: #fff; border-bottom: 1px solid #e0e0e0; padding: 10px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
#traj-title { font-weight: bold; font-size: 15px; color: #1e1e2e; }
#traj-task { font-size: 12px; color: #555; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#step-nav { display: flex; gap: 5px; flex-wrap: wrap; padding: 8px 16px; background: #fafafa; border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }
.step-btn { padding: 4px 9px; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; font-size: 12px; background: #fff; color: #555; }
.step-btn:hover { background: #e8e8e8; }
.step-btn.active { border-color: #6c6cff; background: #ededff; color: #4040cc; font-weight: bold; }
.step-btn.has-flagged { border-color: #e55; background: #ffeaea; color: #c00; }
.step-btn.has-flagged.active { background: #ffd0d0; }
.step-btn.has-nbc { border-color: #e8900a; background: #fff4e0; color: #c07000; }
.step-btn.has-nbc.active { background: #ffe8b0; }

#content { flex: 1; display: flex; overflow: hidden; }
#left-panel { flex: 0 0 50%; border-right: 1px solid #ddd; overflow-y: auto; padding: 14px 16px; background: #fff; }
#right-panel { flex: 0 0 50%; overflow-y: auto; padding: 14px 16px; background: #f9f9f9; }

/* Left panel */
.assistant-text { background: #f0f4ff; border-left: 3px solid #6c6cff; padding: 10px 12px; border-radius: 4px; white-space: pre-wrap; line-height: 1.5; font-size: 13px; }
.section-title { font-size: 11px; font-weight: bold; color: #888; text-transform: uppercase; letter-spacing: .5px; margin: 10px 0 5px; }
.tool-block { border: 1px solid #e0e0e0; border-radius: 5px; margin-bottom: 8px; overflow: hidden; font-size: 12px; }
.tool-header { background: #f0f0f0; padding: 6px 10px; font-weight: bold; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
.tool-header:hover { background: #e4e4e4; }
.tool-body { padding: 8px 10px; background: #fafafa; white-space: pre-wrap; font-family: monospace; font-size: 11px; display: none; max-height: 300px; overflow-y: auto; }
.tool-body.open { display: block; }
.tool-name-call { color: #6c6cff; }
.tool-name-result { color: #3aaa6a; }

/* Right panel */
.claim-card { border: 1px solid #ddd; border-radius: 6px; margin-bottom: 12px; overflow: hidden; background: #fff; }
.claim-header { padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; }
.claim-header.ns { background: #ffeaea; border-bottom: 1px solid #f5c0c0; }
.claim-header.nbc { background: #fff4e0; border-bottom: 1px solid #f5d890; }
.verdict-badge { font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 10px; }
.verdict-badge.ns { background: #f38ba8; color: #1e1e2e; }
.verdict-badge.nbc { background: #fab387; color: #1e1e2e; }
.claim-type-badge { font-size: 10px; padding: 2px 7px; border-radius: 10px; background: #dde3ff; color: #3a3acc; }
.claim-body { padding: 10px 12px; }
.claim-span { font-size: 13px; font-style: italic; color: #333; background: #f5f5f5; padding: 6px 10px; border-radius: 4px; margin-bottom: 8px; line-height: 1.4; }
.ev-section { margin-bottom: 6px; }
.ev-label { font-size: 10px; font-weight: bold; color: #888; text-transform: uppercase; margin-bottom: 2px; }
.ev-value { font-size: 12px; color: #333; }
.ev-ref { font-family: monospace; font-size: 11px; background: #eee; padding: 3px 6px; border-radius: 3px; display: inline-block; max-width: 100%; white-space: pre-wrap; word-break: break-all; }
.reason-text { font-size: 12px; color: #444; line-height: 1.5; }

/* Review controls */
.review-controls { margin-top: 10px; padding-top: 8px; border-top: 1px solid #eee; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.review-btn { padding: 4px 12px; border-radius: 4px; border: 1px solid #ccc; cursor: pointer; font-size: 12px; background: #f5f5f5; }
.review-btn.ok { border-color: #3aaa6a; color: #1a7a40; }
.review-btn.ok:hover, .review-btn.ok.selected { background: #e0f7ea; }
.review-btn.fp { border-color: #e55; color: #c00; }
.review-btn.fp:hover, .review-btn.fp.selected { background: #ffeaea; }
.review-btn.skip { border-color: #bbb; }
.review-btn.skip.selected { background: #eee; }
.ha-type-select { font-size: 12px; padding: 3px 7px; border-radius: 4px; border: 1px solid #ccc; background: #fff; }
.review-note { font-size: 11px; color: #aaa; margin-left: 4px; }

/* Export */
#export-bar { background: #fff; border-top: 1px solid #e0e0e0; padding: 8px 16px; display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
#export-btn { padding: 6px 16px; background: #6c6cff; color: #fff; border: none; border-radius: 5px; cursor: pointer; font-size: 13px; }
#export-btn:hover { background: #5555dd; }
#progress-text { font-size: 12px; color: #666; }

#empty-state { padding: 40px; color: #aaa; text-align: center; }

/* Claim span highlights in assistant text */
mark.hl-ns  { background: #ffb3b3; color: inherit; border-radius: 2px; padding: 0 1px; cursor: default; }
mark.hl-nbc { background: #ffd9a0; color: inherit; border-radius: 2px; padding: 0 1px; cursor: default; }

/* Evidence snippet inline in claim card */
.ev-snippet-wrap { margin-top: 6px; border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden; }
.ev-snippet-header { background: #f0f0f0; padding: 4px 8px; font-size: 10px; font-weight: bold; color: #666; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
.ev-snippet-header:hover { background: #e4e4e4; }
.ev-snippet-body { display: none; padding: 6px 8px; background: #fafafa; font-family: monospace; font-size: 10px; white-space: pre-wrap; max-height: 200px; overflow-y: auto; word-break: break-all; }
.ev-snippet-body.open { display: block; }
.step-jump-btn { font-size: 10px; padding: 1px 7px; border: 1px solid #6c6cff; border-radius: 8px; background: #ededff; color: #4040cc; cursor: pointer; white-space: nowrap; }
.step-jump-btn:hover { background: #dde3ff; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #ccc; border-radius: 3px; }
</style>
</head>
<body>
<div id="app">
  <div id="sidebar">
    <div id="sidebar-header">
      📋 SIDEBAR_TITLE
      <div style="font-size:11px;color:#6c7086;font-weight:normal;margin-top:3px;">TRAJS_COUNT trajectories · CLAIMS_COUNT flagged</div>
    </div>
    <div id="traj-list"></div>
  </div>
  <div id="main">
    <div id="top-bar">
      <span id="traj-title">Select a trajectory</span>
      <span id="traj-task"></span>
    </div>
    <div id="step-nav"></div>
    <div id="content">
      <div id="left-panel"><div id="empty-state">Select a trajectory from the sidebar</div></div>
      <div id="right-panel"></div>
    </div>
    <div id="export-bar">
      <button id="export-btn" onclick="exportResults()">Export Review JSON</button>
      <span id="progress-text"></span>
    </div>
  </div>
</div>

<script>
const TRAJS = /*TRAJS_DATA*/;

// Review state: claim_id -> {status: 'ok'|'fp'|'skip', ha_type?, note?}
const reviewState = {};

let currentTrajIdx = -1;
let currentStepIdx = 0;

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Highlight flagged claim spans inside assistant text.
// Returns HTML with <mark> tags injected; the rest is HTML-escaped.
function highlightClaims(text, claims) {
  if (!claims || claims.length === 0) return escHtml(text);

  // Strip surrounding curly/straight quotes the Stage 1 extractor often adds
  const stripQuotes = s => s.replace(/^[“”‘’"'\-\s]+|[“”‘’"'\-\s]+$/g, '').trim();

  // Find each span in the text (case-insensitive substring match)
  const segments = []; // {start, end, verdict}
  for (const c of claims) {
    const needle = stripQuotes(c.claim_span);
    if (!needle) continue;
    const idx = text.toLowerCase().indexOf(needle.toLowerCase());
    if (idx < 0) continue;
    segments.push({start: idx, end: idx + needle.length, verdict: c.verdict});
  }
  if (segments.length === 0) return escHtml(text);

  // Sort by position; drop overlapping segments
  segments.sort((a, b) => a.start - b.start);
  const merged = [];
  for (const seg of segments) {
    if (merged.length && seg.start < merged[merged.length-1].end) continue;
    merged.push(seg);
  }

  let html = '';
  let pos = 0;
  for (const {start, end, verdict} of merged) {
    html += escHtml(text.slice(pos, start));
    const cls = verdict === 'not_supported' ? 'hl-ns' : 'hl-nbc';
    html += `<mark class="${cls}" title="${verdict}">${escHtml(text.slice(start, end))}</mark>`;
    pos = end;
  }
  html += escHtml(text.slice(pos));
  return html;
}

// ── Sidebar ────────────────────────────────────────────────────────────────────
function buildSidebar() {
  const list = document.getElementById('traj-list');
  list.innerHTML = TRAJS.map((t, i) => {
    const ns = t.not_supported_count;
    const nbc = t.needs_broader_context_count;
    const badges = (ns ? `<span class="badge badge-ns">${ns} NS</span>` : '') +
                   (nbc ? `<span class="badge badge-nbc">${nbc} NBC</span>` : '');
    return `<div class="traj-item" id="ti-${i}" onclick="selectTraj(${i})">
      <div>
        <div class="traj-label">${escHtml(t.label)}</div>
        <div class="traj-split">${escHtml(t.split)}</div>
      </div>
      <div class="traj-counts">${badges}</div>
    </div>`;
  }).join('');
}

// ── Select trajectory ──────────────────────────────────────────────────────────
function selectTraj(idx) {
  if (currentTrajIdx === idx) return;
  if (currentTrajIdx >= 0) document.getElementById(`ti-${currentTrajIdx}`)?.classList.remove('active');
  currentTrajIdx = idx;
  currentStepIdx = 0;
  document.getElementById(`ti-${idx}`)?.classList.add('active');

  const t = TRAJS[idx];
  document.getElementById('traj-title').textContent = t.label;
  document.getElementById('traj-task').textContent = t.task || '';

  buildStepNav(t);
  // Jump to first flagged step
  const firstFlagged = t.steps.findIndex(s => s.flagged_claims.length > 0);
  selectStep(firstFlagged >= 0 ? firstFlagged : 0);
}

// ── Step navigation ────────────────────────────────────────────────────────────
function buildStepNav(t) {
  const nav = document.getElementById('step-nav');
  nav.innerHTML = t.steps.map((s, i) => {
    const nsCount = s.flagged_claims.filter(c => c.verdict === 'not_supported').length;
    const nbcCount = s.flagged_claims.filter(c => c.verdict === 'needs_broader_context').length;
    let cls = 'step-btn';
    if (nsCount > 0) cls += ' has-flagged';
    else if (nbcCount > 0) cls += ' has-nbc';
    const badge = nsCount || nbcCount ? ` (${nsCount+nbcCount})` : '';
    return `<button class="${cls}" id="sb-${i}" onclick="selectStep(${i})">S${s.step_id}${badge}</button>`;
  }).join('');
}

function selectStep(i) {
  const t = TRAJS[currentTrajIdx];
  if (!t) return;
  // Update button active state
  document.querySelectorAll('.step-btn').forEach((b, j) => {
    b.classList.toggle('active', j === i);
  });
  currentStepIdx = i;
  renderStep(t.steps[i]);
}

// ── Render step ────────────────────────────────────────────────────────────────
function renderStep(step) {
  renderLeft(step);
  renderRight(step);
}

function renderLeft(step) {
  const lp = document.getElementById('left-panel');
  let html = '';

  // Assistant text — flagged spans highlighted
  html += `<div class="section-title">Assistant Text</div>`;
  const atText = step.assistant_text || '(empty)';
  html += `<div class="assistant-text">${highlightClaims(atText, step.flagged_claims)}</div>`;

  // Tool calls
  if (step.tool_calls && step.tool_calls.length > 0) {
    html += `<div class="section-title">Tool Calls</div>`;
    step.tool_calls.forEach((tc, i) => {
      const params = JSON.stringify(tc.parameters || {}, null, 2);
      const uid = `tc-${step.step_id}-${i}`;
      html += `<div class="tool-block">
        <div class="tool-header" onclick="toggleBlock('${uid}')">
          <span class="tool-name-call">📤 ${escHtml(tc.tool_name)}</span>
          <span style="font-size:11px;color:#888">▼</span>
        </div>
        <div class="tool-body" id="${uid}">${escHtml(params)}</div>
      </div>`;
    });
  }

  // Tool results
  if (step.tool_results && step.tool_results.length > 0) {
    html += `<div class="section-title">Tool Results</div>`;
    step.tool_results.forEach((tr, i) => {
      const result = JSON.stringify(tr.result || {}, null, 2);
      const uid = `tr-${step.step_id}-${i}`;
      html += `<div class="tool-block">
        <div class="tool-header" onclick="toggleBlock('${uid}')">
          <span class="tool-name-result">📥 ${escHtml(tr.tool_name)}</span>
          <span style="font-size:11px;color:#888">▼</span>
        </div>
        <div class="tool-body" id="${uid}">${escHtml(result)}</div>
      </div>`;
    });
  }

  lp.innerHTML = html;
}

function toggleBlock(uid) {
  const el = document.getElementById(uid);
  if (el) el.classList.toggle('open');
}

function renderRight(step) {
  const rp = document.getElementById('right-panel');
  if (!step.flagged_claims || step.flagged_claims.length === 0) {
    rp.innerHTML = `<div style="padding:30px;color:#aaa;text-align:center;">No flagged claims in this step</div>`;
    return;
  }

  const html = step.flagged_claims.map(c => {
    const isNS = c.verdict === 'not_supported';
    const cls = isNS ? 'ns' : 'nbc';
    const verdictLabel = isNS ? 'not_supported' : 'needs_broader_context';
    const ev = c.evidence_pointer || {};
    const cid = c.claim_id;
    const rv = reviewState[cid] || {};

    return `<div class="claim-card" id="card-${escHtml(cid)}">
      <div class="claim-header ${cls}">
        <div style="display:flex;gap:6px;align-items:center;">
          <span class="verdict-badge ${cls}">${verdictLabel}</span>
          <span class="claim-type-badge">${escHtml(c.claim_type || '')}</span>
        </div>
        <span style="font-size:10px;color:#888;">${escHtml(cid.split('__')[1] || '')}</span>
      </div>
      <div class="claim-body">
        <div class="ev-section">
          <div class="ev-label">Claim Span</div>
          <div class="claim-span">"${escHtml(c.claim_span)}"</div>
        </div>
        ${ev.channel ? `<div class="ev-section">
          <div class="ev-label">Evidence</div>
          <div class="ev-value" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span><b>channel:</b> ${escHtml(ev.channel)}</span>
            ${ev.step != null ? '<span>· <b>step:</b> ' + escHtml(String(ev.step)) + '</span>' +
              (ev.step !== step.step_id ? '<button class="step-jump-btn" onclick="jumpToEvidenceStep(' + ev.step + ')">→ Go to S' + ev.step + '</button>' : '') : ''}
          </div>
          ${ev.ref ? `<div style="margin-top:4px;"><span class="ev-ref">${escHtml(ev.ref)}</span></div>` : ''}
        </div>
        ${c._evidence_snippet ? renderSnippet(cid, c._evidence_snippet, ev.step) : ''}` : ''}
        <div class="ev-section">
          <div class="ev-label">Reason</div>
          <div class="reason-text">${escHtml(c.reason)}</div>
        </div>
        <div class="review-controls">
          <button class="review-btn ok ${rv.status==='ok'?'selected':''}"
            onclick="setReview('${escHtml(cid)}', 'ok')">✓ Correct</button>
          <button class="review-btn fp ${rv.status==='fp'?'selected':''}"
            onclick="setReview('${escHtml(cid)}', 'fp')">✗ False Positive</button>
          <button class="review-btn skip ${rv.status==='skip'?'selected':''}"
            onclick="setReview('${escHtml(cid)}', 'skip')">— Skip</button>
          ${(rv.status === 'ok' && isNS) || rv.status === 'fp' ? renderHaSelect(cid, rv) : ''}
        </div>
      </div>
    </div>`;
  }).join('');

  rp.innerHTML = html;
  updateProgress();
}

function renderHaSelect(cid, rv) {
  const options = [
    ['', '-- HA type --'],
    ['no-action', '行动缺失 (No Action)'],
    ['wrong-action', '行动偏差 (Wrong Action)'],
    ['false-result', '结果虚报 (False Result)'],
    ['constraint-viol', '约束违规 (Constraint Violation)'],
    ['annotation-error', '标注错误 (Annotation Error)'],
  ];
  const opts = options.map(([v, l]) =>
    `<option value="${v}" ${rv.ha_type===v?'selected':''}>${l}</option>`
  ).join('');
  return `<select class="ha-type-select" onchange="setHaType('${escHtml(cid)}', this.value)">${opts}</select>`;
}

function renderSnippet(cid, snippet, evStep) {
  const uid = `snip-${cid.replace(/[^a-z0-9]/gi,'_')}`;
  return `<div class="ev-snippet-wrap">
    <div class="ev-snippet-header" onclick="toggleBlock('${uid}')">
      <span>📄 Raw evidence (S${evStep})</span><span>▼</span>
    </div>
    <div class="ev-snippet-body" id="${uid}">${escHtml(snippet)}</div>
  </div>`;
}

function jumpToEvidenceStep(targetStepId) {
  const t = TRAJS[currentTrajIdx];
  if (!t) return;
  const idx = t.steps.findIndex(s => s.step_id === targetStepId);
  if (idx < 0) return;
  selectStep(idx);
  // After render, expand all tool blocks in that step and scroll left panel to top
  setTimeout(() => {
    document.getElementById('left-panel').scrollTop = 0;
    document.querySelectorAll('.tool-body').forEach(el => el.classList.add('open'));
  }, 50);
}

function setReview(cid, status) {
  if (!reviewState[cid]) reviewState[cid] = {};
  reviewState[cid].status = status;
  // Re-render right panel to update button state + potentially show ha-type
  if (currentTrajIdx >= 0) {
    renderRight(TRAJS[currentTrajIdx].steps[currentStepIdx]);
  }
  updateProgress();
}

function setHaType(cid, haType) {
  if (!reviewState[cid]) reviewState[cid] = {};
  reviewState[cid].ha_type = haType;
}

// ── Progress ───────────────────────────────────────────────────────────────────
function updateProgress() {
  const allFlagged = TRAJS.flatMap(t => t.steps.flatMap(s => s.flagged_claims));
  const reviewed = allFlagged.filter(c => reviewState[c.claim_id]?.status).length;
  document.getElementById('progress-text').textContent =
    `${reviewed} / ${allFlagged.length} reviewed`;
}

// ── Export ─────────────────────────────────────────────────────────────────────
function exportResults() {
  const allFlagged = TRAJS.flatMap(t => t.steps.flatMap(s =>
    s.flagged_claims.map(c => ({
      claim_id: c.claim_id,
      traj_label: t.label,
      split: t.split,
      step_id: c.step_id,
      claim_span: c.claim_span,
      claim_type: c.claim_type,
      verdict: c.verdict,
      reason: c.reason,
      evidence_pointer: c.evidence_pointer,
      review: reviewState[c.claim_id] || null,
    }))
  ));
  const blob = new Blob([JSON.stringify(allFlagged, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'binary_review_results.json';
  a.click();
}

// ── Init ───────────────────────────────────────────────────────────────────────
buildSidebar();
updateProgress();
</script>
</body>
</html>
"""


def _verdict_cls(v: str) -> str:
    return "ns" if v == "not_supported" else "nbc"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results-dir", default="binary_results",
                   help="Verdict dir name under stage2/ (default: binary_results).")
    p.add_argument("--exp-root", default="experiments_v2/real",
                   help="Trajectory root (relative to research/, default: experiments_v2/real).")
    p.add_argument("--output-html", default="binary_review_ui.html",
                   help="Output HTML filename (written under stage2/).")
    p.add_argument("--title-suffix", default="",
                   help="Suffix appended to the page title and sidebar heading "
                        "for disambiguation across models (e.g. 'DeepSeek Reasoner').")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    results_dir = SCRIPT_DIR / args.results_dir
    exp_root = RESEARCH / args.exp_root
    out_html = SCRIPT_DIR / args.output_html

    if args.title_suffix:
        page_title = f"Binary Stage 2 Review UI — {args.title_suffix}"
        sidebar_title = f"Binary Review UI · {args.title_suffix}"
    else:
        page_title = "Binary Stage 2 Review UI"
        sidebar_title = "Binary Review UI"

    print(f"Results dir: {results_dir}")
    print(f"Exp root:    {exp_root}")
    print(f"Output HTML: {out_html}")
    print(f"Title:       {page_title}")
    print("Loading trajectories…")
    trajs = _load_flagged(results_dir, exp_root)
    print(f"  {len(trajs)} trajectories, "
          f"{sum(t['total_flagged'] for t in trajs)} flagged claims")

    data_js = json.dumps(trajs, ensure_ascii=False)

    html = HTML_TEMPLATE.replace("/*TRAJS_DATA*/", data_js)
    html = html.replace("PAGE_TITLE", page_title)
    html = html.replace("SIDEBAR_TITLE", sidebar_title)
    html = html.replace("TRAJS_COUNT", str(len(trajs)))
    html = html.replace("CLAIMS_COUNT", str(sum(t["total_flagged"] for t in trajs)))

    out_html.write_text(html, encoding="utf-8")
    print(f"Written → {out_html}")


if __name__ == "__main__":
    main()
