"""
Build a self-contained Binary Stage-2 Review UI (single HTML file).

Joins the Stage-2 verdict rows (binary_results[_gpt4o]/{split}/<stem>_verdicts.jsonl)
back to their author trajectories, embeds the data, and writes one HTML file you
can open in any browser. The UI lets a human sweep every *flagged* claim
(verdict != supported), highlights the flagged span inline in the assistant text,
shows the routed evidence, and records ✓correct / ✗false-positive / —skip plus an
HA-type label per claim. Review state persists in localStorage and exports to JSON.

Refinements over the original hand-built deepseek UI:
  - summary stat strip (flagged total, NS/NBC, action-claim gaps),
  - sidebar filter box + "flagged only" toggle,
  - action claims (action_intention/action_completion) tagged ⚡ — the
    claim-action-gap candidates,
  - keyboard nav (←/→ steps, ↑/↓ trajectories, 1/2/3 review the first card),
  - evidence snippet auto-pulled from the trajectory step,
  - localStorage autosave so a refresh never loses progress.

Usage:
  python -m research.eval_v3.stage2.build_review_ui                 # gpt-4o (default)
  python -m research.eval_v3.stage2.build_review_ui --author-model deepseek-chat
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.eval_v3.stage2.run_stage2 import (
    AUTHOR_CONFIGS, index_trajectories, _parse_stage1_name,
)

HERE = Path(__file__).resolve().parent

# Per-author UI config: where the verdicts live, output file, and a display title.
UI_CONFIGS: dict[str, dict] = {
    "gpt-4o": {
        "verdicts_dir": "binary_results_gpt4o",
        "out_name": "gpt4o_review_ui.html",
        "title": "GPT-4o",
    },
    "deepseek-chat": {
        "verdicts_dir": "binary_results",
        "out_name": "gpt4o_review_ui_deepseek.html",
        "title": "DeepSeek Chat",
    },
}

FLAGGED = {"not_supported", "needs_broader_context"}
ACTION_TYPES = {"action_intention", "action_completion"}


def load_verdicts(verdicts_dir: Path) -> dict[tuple[str, str], list[dict]]:
    """(split, stem) -> list of verdict rows."""
    out: dict[tuple[str, str], list[dict]] = {}
    for split in ("dependent", "independent"):
        for f in sorted((verdicts_dir / split).glob("*_verdicts.jsonl")):
            stem = f.name.replace("_verdicts.jsonl", "")
            rows = [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]
            out[(split, stem)] = rows
    return out


def _evidence_snippet(traj_steps: dict[int, dict], ev: dict) -> str | None:
    """Pull the raw channel content at the evidence-pointer step, JSON-dumped."""
    if not ev or ev.get("step") is None:
        return None
    step = traj_steps.get(int(ev["step"]))
    if not step:
        return None
    channel = ev.get("channel")
    payload = None
    if channel == "tool_results":
        payload = step.get("tool_results")
    elif channel == "tool_calls":
        payload = step.get("tool_calls")
    if not payload:
        return None
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return text[:4000] + ("\n… (truncated)" if len(text) > 4000 else "")


def build_trajs(verdicts: dict, indep_traj: dict, dep_traj: dict) -> list[dict]:
    trajs: list[dict] = []
    for (split, stem), rows in sorted(verdicts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        pair, task = _parse_stage1_name(stem)
        traj_path = indep_traj.get(task) if split == "independent" else dep_traj.get((pair, task))
        if traj_path is None:
            print(f"  [skip] {split}/{stem}: no trajectory for ({pair!r},{task!r})")
            continue
        traj = json.loads(traj_path.read_text(encoding="utf-8"))
        by_step = {s["step_id"]: s for s in traj["steps"]}

        # Group *every* claim (supported + flagged) by the step it was narrated in.
        claims_by_step: dict[int, list[dict]] = {}
        ns = nbc = sup = 0
        for r in rows:
            v = r.get("verdict")
            ns += v == "not_supported"
            nbc += v == "needs_broader_context"
            sup += v == "supported"
            snippet = _evidence_snippet(by_step, r.get("evidence_pointer") or {})
            claims_by_step.setdefault(r["step_id"], []).append({
                "claim_id": r["claim_id"],
                "step_id": r["step_id"],
                "claim_span": r.get("claim_span", ""),
                "claim_type": r.get("claim_type", ""),
                "verdict": v,
                "reason": r.get("reason", ""),
                "evidence_pointer": r.get("evidence_pointer"),
                "is_action": r.get("claim_type") in ACTION_TYPES,
                "_evidence_snippet": snippet,
            })

        steps = []
        for s in traj["steps"]:
            steps.append({
                "step_id": s["step_id"],
                "assistant_text": s.get("assistant_text", ""),
                "tool_calls": s.get("tool_calls") or [],
                "tool_results": s.get("tool_results") or [],
                "claims": claims_by_step.get(s["step_id"], []),
            })

        trajs.append({
            "split": split,
            "label": stem.replace("_gemini-pro_v1", ""),
            "traj_id": traj.get("trajectory_id", ""),
            "task_id": traj.get("task_id", task),
            "task": traj.get("task", ""),
            "steps": steps,
            "not_supported_count": ns,
            "needs_broader_context_count": nbc,
            "supported_count": sup,
        })
    return trajs


# ── HTML template ────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Binary Stage 2 Review UI — __TITLE__</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; background: #f5f5f7; color: #1e1e2e; }

#app { display: flex; height: 100vh; }
#sidebar { width: 270px; min-width: 210px; background: #1e1e2e; color: #cdd6f4; display: flex; flex-direction: column; overflow: hidden; }
#sidebar-header { padding: 12px 14px; background: #181825; border-bottom: 1px solid #313244; flex-shrink: 0; }
#sidebar-header .title { font-weight: bold; font-size: 14px; }
#sidebar-header .sub { font-size: 11px; color: #9399b2; margin-top: 3px; }
.stat-strip { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.stat { background: #313244; border-radius: 6px; padding: 4px 8px; font-size: 11px; line-height: 1.2; }
.stat b { font-size: 14px; display: block; }
.stat.ns b { color: #f38ba8; } .stat.nbc b { color: #fab387; } .stat.act b { color: #89dceb; } .stat.sup b { color: #a6e3a1; }
#filter-box { margin: 8px 0 0; }
#filter-input { width: 100%; padding: 5px 8px; border-radius: 5px; border: 1px solid #45475a; background: #11111b; color: #cdd6f4; font-size: 12px; }
#filter-input::placeholder { color: #6c7086; }
.toggle-row { display: flex; align-items: center; gap: 5px; margin-top: 7px; font-size: 11px; color: #9399b2; cursor: pointer; user-select: none; }
#traj-list { flex: 1; overflow-y: auto; }
.traj-item { padding: 9px 14px; cursor: pointer; border-bottom: 1px solid #313244; display: flex; justify-content: space-between; align-items: flex-start; gap: 6px; }
.traj-item:hover { background: #313244; }
.traj-item.active { background: #45475a; }
.traj-item.done .traj-label::after { content: " ✓"; color: #a6e3a1; }
.traj-label { font-size: 12px; font-weight: 600; }
.traj-split { font-size: 10px; color: #6c7086; margin-top: 2px; }
.traj-counts { display: flex; gap: 4px; flex-shrink: 0; align-items: center; margin-top: 1px; }
.badge { font-size: 10px; padding: 1px 5px; border-radius: 9px; font-weight: bold; }
.badge-ns { background: #f38ba8; color: #1e1e2e; }
.badge-nbc { background: #fab387; color: #1e1e2e; }
.badge-sup { background: #45475a; color: #a6e3a1; }

#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#top-bar { background: #fff; border-bottom: 1px solid #e0e0e0; padding: 10px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
#traj-title { font-weight: bold; font-size: 15px; }
#traj-task { font-size: 12px; color: #555; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kbd-hint { font-size: 10px; color: #aaa; white-space: nowrap; }
.kbd-hint kbd { background: #eee; border: 1px solid #ccc; border-bottom-width: 2px; border-radius: 3px; padding: 0 4px; font-family: monospace; }
#step-nav { display: flex; gap: 5px; flex-wrap: wrap; padding: 8px 16px; background: #fafafa; border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }
.step-btn { padding: 4px 9px; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; font-size: 12px; background: #fff; color: #555; }
.step-btn:hover { background: #e8e8e8; }
.step-btn.active { border-color: #6c6cff; background: #ededff; color: #4040cc; font-weight: bold; }
.step-btn.has-flagged { border-color: #e55; background: #ffeaea; color: #c00; }
.step-btn.has-flagged.active { background: #ffd0d0; }
.step-btn.has-nbc { border-color: #e8900a; background: #fff4e0; color: #c07000; }
.step-btn.has-nbc.active { background: #ffe8b0; }
.step-btn.has-sup { border-color: #9ccc9c; color: #2a7a40; }
.step-btn.has-sup.active { background: #e0f7ea; }

#content { flex: 1; display: flex; overflow: hidden; }
#left-panel { flex: 0 0 50%; border-right: 1px solid #ddd; overflow-y: auto; padding: 14px 16px; background: #fff; }
#right-panel { flex: 0 0 50%; overflow-y: auto; padding: 14px 16px; background: #f9f9fb; }

.assistant-text { background: #f0f4ff; border-left: 3px solid #6c6cff; padding: 10px 12px; border-radius: 4px; white-space: pre-wrap; line-height: 1.5; font-size: 13px; }
.section-title { font-size: 11px; font-weight: bold; color: #888; text-transform: uppercase; letter-spacing: .5px; margin: 10px 0 5px; }
.tool-block { border: 1px solid #e0e0e0; border-radius: 5px; margin-bottom: 8px; overflow: hidden; font-size: 12px; }
.tool-header { background: #f0f0f0; padding: 6px 10px; font-weight: bold; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
.tool-header:hover { background: #e4e4e4; }
.tool-body { padding: 8px 10px; background: #fafafa; white-space: pre-wrap; font-family: monospace; font-size: 11px; display: none; max-height: 320px; overflow-y: auto; }
.tool-body.open { display: block; }
.tool-name-call { color: #6c6cff; }
.tool-name-result { color: #3aaa6a; }

.claim-card { border: 1px solid #ddd; border-radius: 6px; margin-bottom: 12px; overflow: hidden; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
.claim-card.focused { box-shadow: 0 0 0 2px #6c6cff; }
.claim-header { padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; }
.claim-header.ns { background: #ffeaea; border-bottom: 1px solid #f5c0c0; }
.claim-header.nbc { background: #fff4e0; border-bottom: 1px solid #f5d890; }
.claim-header.sup { background: #eefaf0; border-bottom: 1px solid #c8ecd2; }
.claim-card.sup { opacity: .92; }
.verdict-badge { font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 10px; }
.verdict-badge.ns { background: #f38ba8; color: #1e1e2e; }
.verdict-badge.nbc { background: #fab387; color: #1e1e2e; }
.verdict-badge.sup { background: #a6e3a1; color: #1e3a24; }
.claim-type-badge { font-size: 10px; padding: 2px 7px; border-radius: 10px; background: #dde3ff; color: #3a3acc; }
.action-tag { font-size: 10px; padding: 2px 7px; border-radius: 10px; background: #cdeffd; color: #0673a3; font-weight: bold; }
.claim-body { padding: 10px 12px; }
.claim-span { font-size: 13px; font-style: italic; color: #333; background: #f5f5f5; padding: 6px 10px; border-radius: 4px; margin-bottom: 8px; line-height: 1.4; }
.ev-section { margin-bottom: 6px; }
.ev-label { font-size: 10px; font-weight: bold; color: #888; text-transform: uppercase; margin-bottom: 2px; }
.ev-value { font-size: 12px; color: #333; }
.ev-ref { font-family: monospace; font-size: 11px; background: #eee; padding: 3px 6px; border-radius: 3px; display: inline-block; max-width: 100%; white-space: pre-wrap; word-break: break-all; }
.reason-text { font-size: 12px; color: #444; line-height: 1.5; }

.review-controls { margin-top: 10px; padding-top: 8px; border-top: 1px solid #eee; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.review-btn { padding: 4px 12px; border-radius: 4px; border: 1px solid #ccc; cursor: pointer; font-size: 12px; background: #f5f5f5; }
.review-btn.ok { border-color: #3aaa6a; color: #1a7a40; }
.review-btn.ok:hover, .review-btn.ok.selected { background: #e0f7ea; }
.review-btn.fp { border-color: #e55; color: #c00; }
.review-btn.fp:hover, .review-btn.fp.selected { background: #ffeaea; }
.review-btn.skip { border-color: #bbb; }
.review-btn.skip.selected { background: #eee; }
.ha-type-select { font-size: 12px; padding: 3px 7px; border-radius: 4px; border: 1px solid #ccc; background: #fff; }

#export-bar { background: #fff; border-top: 1px solid #e0e0e0; padding: 8px 16px; display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
#export-btn { padding: 6px 16px; background: #6c6cff; color: #fff; border: none; border-radius: 5px; cursor: pointer; font-size: 13px; }
#export-btn:hover { background: #5555dd; }
.ghost-btn { padding: 6px 12px; background: #fff; color: #666; border: 1px solid #ccc; border-radius: 5px; cursor: pointer; font-size: 12px; }
.ghost-btn:hover { background: #f0f0f0; }
#progress-text { font-size: 12px; color: #666; }
#progress-bar { flex: 1; height: 6px; background: #eee; border-radius: 3px; overflow: hidden; max-width: 240px; }
#progress-fill { height: 100%; background: #6c6cff; width: 0; transition: width .2s; }

#empty-state { padding: 40px; color: #aaa; text-align: center; }
mark.hl-ns  { background: #ffb3b3; border-radius: 2px; padding: 0 1px; }
mark.hl-nbc { background: #ffd9a0; border-radius: 2px; padding: 0 1px; }
mark.hl-sup { background: #c7f0d0; border-radius: 2px; padding: 0 1px; }

.ev-snippet-wrap { margin-top: 6px; border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden; }
.ev-snippet-header { background: #f0f0f0; padding: 4px 8px; font-size: 10px; font-weight: bold; color: #666; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
.ev-snippet-header:hover { background: #e4e4e4; }
.ev-snippet-body { display: none; padding: 6px 8px; background: #fafafa; font-family: monospace; font-size: 10px; white-space: pre-wrap; max-height: 240px; overflow-y: auto; word-break: break-all; }
.ev-snippet-body.open { display: block; }
.step-jump-btn { font-size: 10px; padding: 1px 7px; border: 1px solid #6c6cff; border-radius: 8px; background: #ededff; color: #4040cc; cursor: pointer; white-space: nowrap; }
.step-jump-btn:hover { background: #dde3ff; }

::-webkit-scrollbar { width: 7px; height: 7px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #ccc; border-radius: 3px; }
</style>
</head>
<body>
<div id="app">
  <div id="sidebar">
    <div id="sidebar-header">
      <div class="title">📋 Binary Review · __TITLE__</div>
      <div class="sub" id="sub-counts"></div>
      <div class="stat-strip" id="stat-strip"></div>
      <div id="filter-box"><input id="filter-input" placeholder="filter trajectories…" oninput="applyFilter(this.value)"/></div>
      <label class="toggle-row"><input type="checkbox" id="flagged-only" onchange="rebuildSidebar()"/> flagged only (NS/NBC)</label>
      <label class="toggle-row" style="margin-top:4px;"><input type="checkbox" id="action-only" onchange="rebuildSidebar()"/> action claims only</label>
    </div>
    <div id="traj-list"></div>
  </div>
  <div id="main">
    <div id="top-bar">
      <span id="traj-title">Select a trajectory</span>
      <span id="traj-task"></span>
      <span class="kbd-hint"><kbd>←</kbd><kbd>→</kbd> step · <kbd>↑</kbd><kbd>↓</kbd> traj · <kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> review</span>
    </div>
    <div id="step-nav"></div>
    <div id="content">
      <div id="left-panel"><div id="empty-state">Select a trajectory from the sidebar</div></div>
      <div id="right-panel"></div>
    </div>
    <div id="export-bar">
      <button id="export-btn" onclick="exportResults()">⬇ Export Review JSON</button>
      <button class="ghost-btn" onclick="clearReview()">Reset</button>
      <span id="progress-text"></span>
      <div id="progress-bar"><div id="progress-fill"></div></div>
    </div>
  </div>
</div>

<script>
const TRAJS = __DATA__;
const STORAGE_KEY = "__STORAGE_KEY__";

// Review state: claim_id -> {status:'ok'|'fp'|'skip', ha_type?}
let reviewState = {};
try { reviewState = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; } catch (e) { reviewState = {}; }
function saveState() { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(reviewState)); } catch (e) {} }

let currentTrajIdx = -1;
let currentStepIdx = 0;
let actionOnly = false;
let flaggedOnly = false;
let filterText = "";

const FLAGGED = new Set(['not_supported', 'needs_broader_context']);
const vClass = v => v === 'not_supported' ? 'ns' : v === 'needs_broader_context' ? 'nbc' : 'sup';

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Which claims show, given the flagged-only / action-only toggles.
function visClaims(step) {
  let cs = step.claims;
  if (flaggedOnly) cs = cs.filter(c => FLAGGED.has(c.verdict));
  if (actionOnly) cs = cs.filter(c => c.is_action);
  return cs;
}
function trajVisible(t) {
  if (t.steps.every(s => visClaims(s).length === 0)) return false;
  if (!filterText) return true;
  const hay = (t.label + ' ' + t.split + ' ' + (t.task || '')).toLowerCase();
  return hay.includes(filterText);
}

function highlightClaims(text, claims) {
  if (!claims || claims.length === 0) return escHtml(text);
  const stripQuotes = s => s.replace(/^[“”‘’"'\-\s]+|[“”‘’"'\-\s]+$/g, '').trim();
  const segments = [];
  for (const c of claims) {
    const needle = stripQuotes(c.claim_span);
    if (!needle) continue;
    const idx = text.toLowerCase().indexOf(needle.toLowerCase());
    if (idx < 0) continue;
    segments.push({start: idx, end: idx + needle.length, verdict: c.verdict});
  }
  if (segments.length === 0) return escHtml(text);
  // Flagged spans win over supported when they overlap.
  segments.sort((a, b) => a.start - b.start || (FLAGGED.has(b.verdict) - FLAGGED.has(a.verdict)));
  const merged = [];
  for (const seg of segments) {
    if (merged.length && seg.start < merged[merged.length-1].end) continue;
    merged.push(seg);
  }
  let html = '', pos = 0;
  for (const {start, end, verdict} of merged) {
    html += escHtml(text.slice(pos, start));
    html += `<mark class="hl-${vClass(verdict)}" title="${verdict}">${escHtml(text.slice(start, end))}</mark>`;
    pos = end;
  }
  html += escHtml(text.slice(pos));
  return html;
}

// ── Header stats ────────────────────────────────────────────────────────────────
function buildStats() {
  const all = TRAJS.flatMap(t => t.steps.flatMap(s => s.claims));
  const ns = all.filter(c => c.verdict === 'not_supported').length;
  const nbc = all.filter(c => c.verdict === 'needs_broader_context').length;
  const sup = all.filter(c => c.verdict === 'supported').length;
  const actGap = all.filter(c => c.is_action && c.verdict === 'not_supported').length;
  document.getElementById('sub-counts').textContent =
    `${TRAJS.length} trajectories · ${all.length} claims`;
  document.getElementById('stat-strip').innerHTML =
    `<div class="stat ns"><b>${ns}</b>not_supported</div>` +
    `<div class="stat nbc"><b>${nbc}</b>needs_context</div>` +
    `<div class="stat sup"><b>${sup}</b>supported</div>` +
    `<div class="stat act"><b>${actGap}</b>action gap</div>`;
}

// ── Sidebar ─────────────────────────────────────────────────────────────────────
function trajDone(t) {
  const claims = t.steps.flatMap(s => visClaims(s));
  return claims.length > 0 && claims.every(c => reviewState[c.claim_id]?.status);
}
function buildSidebar() {
  const list = document.getElementById('traj-list');
  list.innerHTML = TRAJS.map((t, i) => {
    if (!trajVisible(t)) return '';
    const claims = t.steps.flatMap(s => visClaims(s));
    const ns = claims.filter(c => c.verdict === 'not_supported').length;
    const nbc = claims.filter(c => c.verdict === 'needs_broader_context').length;
    const sup = claims.filter(c => c.verdict === 'supported').length;
    const badges = (ns ? `<span class="badge badge-ns">${ns} NS</span>` : '') +
                   (nbc ? `<span class="badge badge-nbc">${nbc} NBC</span>` : '') +
                   (!ns && !nbc && sup ? `<span class="badge badge-sup">${sup} ✓</span>` : '');
    const done = trajDone(t) ? ' done' : '';
    const active = i === currentTrajIdx ? ' active' : '';
    return `<div class="traj-item${done}${active}" id="ti-${i}" onclick="selectTraj(${i})">
      <div>
        <div class="traj-label">${escHtml(t.label)}</div>
        <div class="traj-split">${escHtml(t.split)}</div>
      </div>
      <div class="traj-counts">${badges}</div>
    </div>`;
  }).join('') || '<div style="padding:14px;color:#6c7086;font-size:12px;">no matches</div>';
}
function rebuildSidebar() {
  actionOnly = document.getElementById('action-only').checked;
  flaggedOnly = document.getElementById('flagged-only').checked;
  buildSidebar();
  if (currentTrajIdx >= 0) { buildStepNav(TRAJS[currentTrajIdx]); renderStep(TRAJS[currentTrajIdx].steps[currentStepIdx]); }
  updateProgress();
}
function applyFilter(v) { filterText = v.trim().toLowerCase(); buildSidebar(); }

// ── Select trajectory ────────────────────────────────────────────────────────────
function selectTraj(idx) {
  if (currentTrajIdx === idx) return;
  document.getElementById(`ti-${currentTrajIdx}`)?.classList.remove('active');
  currentTrajIdx = idx;
  currentStepIdx = 0;
  document.getElementById(`ti-${idx}`)?.classList.add('active');
  const t = TRAJS[idx];
  document.getElementById('traj-title').textContent = t.label;
  document.getElementById('traj-task').textContent = t.task || '';
  buildStepNav(t);
  const firstFlagged = t.steps.findIndex(s => visClaims(s).length > 0);
  selectStep(firstFlagged >= 0 ? firstFlagged : 0);
}

function buildStepNav(t) {
  const nav = document.getElementById('step-nav');
  nav.innerHTML = t.steps.map((s, i) => {
    const claims = visClaims(s);
    const nsCount = claims.filter(c => c.verdict === 'not_supported').length;
    const nbcCount = claims.filter(c => c.verdict === 'needs_broader_context').length;
    let cls = 'step-btn';
    if (nsCount > 0) cls += ' has-flagged';
    else if (nbcCount > 0) cls += ' has-nbc';
    else if (claims.length > 0) cls += ' has-sup';
    const badge = claims.length ? ` (${claims.length})` : '';
    return `<button class="${cls}" id="sb-${i}" onclick="selectStep(${i})">S${s.step_id}${badge}</button>`;
  }).join('');
}

function selectStep(i) {
  const t = TRAJS[currentTrajIdx];
  if (!t) return;
  document.querySelectorAll('.step-btn').forEach((b, j) => b.classList.toggle('active', j === i));
  currentStepIdx = i;
  renderStep(t.steps[i]);
}

function renderStep(step) { renderLeft(step); renderRight(step); }

function renderLeft(step) {
  const lp = document.getElementById('left-panel');
  let html = `<div class="section-title">Assistant Text · S${step.step_id}</div>`;
  const atText = step.assistant_text || '(empty — silent tool call)';
  html += `<div class="assistant-text">${highlightClaims(atText, visClaims(step))}</div>`;
  if (step.tool_calls.length) {
    html += `<div class="section-title">Tool Calls</div>`;
    step.tool_calls.forEach((tc, i) => {
      const uid = `tc-${step.step_id}-${i}`;
      html += `<div class="tool-block">
        <div class="tool-header" onclick="toggleBlock('${uid}')">
          <span class="tool-name-call">📤 ${escHtml(tc.tool_name)}</span><span style="font-size:11px;color:#888">▼</span>
        </div>
        <div class="tool-body" id="${uid}">${escHtml(JSON.stringify(tc.parameters || {}, null, 2))}</div>
      </div>`;
    });
  }
  if (step.tool_results.length) {
    html += `<div class="section-title">Tool Results</div>`;
    step.tool_results.forEach((tr, i) => {
      const uid = `tr-${step.step_id}-${i}`;
      html += `<div class="tool-block">
        <div class="tool-header" onclick="toggleBlock('${uid}')">
          <span class="tool-name-result">📥 ${escHtml(tr.tool_name)}</span><span style="font-size:11px;color:#888">▼</span>
        </div>
        <div class="tool-body" id="${uid}">${escHtml(JSON.stringify(tr.result || {}, null, 2))}</div>
      </div>`;
    });
  }
  lp.innerHTML = html;
}

function toggleBlock(uid) { document.getElementById(uid)?.classList.toggle('open'); }

function renderRight(step) {
  const rp = document.getElementById('right-panel');
  const claims = visClaims(step);
  if (!claims.length) {
    rp.innerHTML = `<div style="padding:30px;color:#aaa;text-align:center;">No claims in this step</div>`;
    updateProgress();
    return;
  }
  rp.innerHTML = claims.map((c, ci) => {
    const isNS = c.verdict === 'not_supported';
    const cls = vClass(c.verdict);
    const ev = c.evidence_pointer || {};
    const cid = c.claim_id;
    const rv = reviewState[cid] || {};
    return `<div class="claim-card ${cls}${ci === 0 ? ' focused' : ''}" id="card-${escHtml(cid)}">
      <div class="claim-header ${cls}">
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <span class="verdict-badge ${cls}">${c.verdict}</span>
          <span class="claim-type-badge">${escHtml(c.claim_type || '')}</span>
          ${c.is_action ? '<span class="action-tag">⚡ ACTION</span>' : ''}
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
          <button class="review-btn ok ${rv.status==='ok'?'selected':''}" onclick="setReview('${escHtml(cid)}','ok')">✓ Correct</button>
          <button class="review-btn fp ${rv.status==='fp'?'selected':''}" onclick="setReview('${escHtml(cid)}','fp')">✗ False Positive</button>
          <button class="review-btn skip ${rv.status==='skip'?'selected':''}" onclick="setReview('${escHtml(cid)}','skip')">— Skip</button>
          ${(rv.status === 'ok' && isNS) || rv.status === 'fp' ? renderHaSelect(cid, rv) : ''}
        </div>
      </div>
    </div>`;
  }).join('');
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
  const opts = options.map(([v, l]) => `<option value="${v}" ${rv.ha_type===v?'selected':''}>${l}</option>`).join('');
  return `<select class="ha-type-select" onchange="setHaType('${escHtml(cid)}', this.value)">${opts}</select>`;
}

function renderSnippet(cid, snippet, evStep) {
  const uid = `snip-${cid.replace(/[^a-z0-9]/gi,'_')}`;
  return `<div class="ev-snippet-wrap">
    <div class="ev-snippet-header" onclick="toggleBlock('${uid}')"><span>📄 Raw evidence (S${evStep})</span><span>▼</span></div>
    <div class="ev-snippet-body" id="${uid}">${escHtml(snippet)}</div>
  </div>`;
}

function jumpToEvidenceStep(targetStepId) {
  const t = TRAJS[currentTrajIdx];
  if (!t) return;
  const idx = t.steps.findIndex(s => s.step_id === targetStepId);
  if (idx < 0) return;
  selectStep(idx);
  setTimeout(() => {
    document.getElementById('left-panel').scrollTop = 0;
    document.querySelectorAll('.tool-body').forEach(el => el.classList.add('open'));
  }, 50);
}

function setReview(cid, status) {
  reviewState[cid] = reviewState[cid] || {};
  reviewState[cid].status = status;
  saveState();
  renderRight(TRAJS[currentTrajIdx].steps[currentStepIdx]);
  document.getElementById(`ti-${currentTrajIdx}`)?.classList.toggle('done', trajDone(TRAJS[currentTrajIdx]));
}
function setHaType(cid, haType) {
  reviewState[cid] = reviewState[cid] || {};
  reviewState[cid].ha_type = haType;
  saveState();
}

function updateProgress() {
  const all = TRAJS.flatMap(t => t.steps.flatMap(s => visClaims(s)));
  const reviewed = all.filter(c => reviewState[c.claim_id]?.status).length;
  document.getElementById('progress-text').textContent = `${reviewed} / ${all.length} reviewed`;
  document.getElementById('progress-fill').style.width = all.length ? `${100*reviewed/all.length}%` : '0';
}

function exportResults() {
  const out = TRAJS.flatMap(t => t.steps.flatMap(s => s.claims.map(c => ({
    claim_id: c.claim_id, traj_label: t.label, split: t.split, step_id: c.step_id,
    claim_span: c.claim_span, claim_type: c.claim_type, is_action: c.is_action,
    verdict: c.verdict, reason: c.reason, evidence_pointer: c.evidence_pointer,
    review: reviewState[c.claim_id] || null,
  }))));
  const blob = new Blob([JSON.stringify(out, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = '__OUTSTEM___review_results.json';
  a.click();
}
function clearReview() {
  if (!confirm('Clear all review marks?')) return;
  reviewState = {}; saveState();
  buildSidebar();
  if (currentTrajIdx >= 0) renderRight(TRAJS[currentTrajIdx].steps[currentStepIdx]);
  updateProgress();
}

// ── Keyboard nav ─────────────────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
  const t = TRAJS[currentTrajIdx];
  const visIdx = TRAJS.map((tt, i) => i).filter(i => trajVisible(TRAJS[i]));
  if (e.key === 'ArrowRight' && t) { if (currentStepIdx < t.steps.length-1) selectStep(currentStepIdx+1); e.preventDefault(); }
  else if (e.key === 'ArrowLeft' && t) { if (currentStepIdx > 0) selectStep(currentStepIdx-1); e.preventDefault(); }
  else if (e.key === 'ArrowDown') { const p = visIdx.indexOf(currentTrajIdx); if (p < visIdx.length-1) selectTraj(visIdx[p+1]); e.preventDefault(); }
  else if (e.key === 'ArrowUp')   { const p = visIdx.indexOf(currentTrajIdx); if (p > 0) selectTraj(visIdx[p-1]); e.preventDefault(); }
  else if (['1','2','3'].includes(e.key) && t) {
    const claims = visClaims(t.steps[currentStepIdx]);
    if (claims.length) { setReview(claims[0].claim_id, {'1':'ok','2':'fp','3':'skip'}[e.key]); }
  }
});

// ── Init ─────────────────────────────────────────────────────────────────────────
buildStats();
buildSidebar();
updateProgress();
const firstVis = TRAJS.findIndex(trajVisible);
if (firstVis >= 0) selectTraj(firstVis);
</script>
</body>
</html>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--author-model", choices=list(UI_CONFIGS), default="gpt-4o")
    p.add_argument("--out", type=Path, default=None,
                   help="Output HTML path (default: <verdicts_dir>/<out_name>).")
    args = p.parse_args()

    ui = UI_CONFIGS[args.author_model]
    verdicts_dir = HERE / ui["verdicts_dir"]
    out_path = args.out or (verdicts_dir / ui["out_name"])

    indep_traj, dep_traj = index_trajectories(AUTHOR_CONFIGS[args.author_model])
    verdicts = load_verdicts(verdicts_dir)
    trajs = build_trajs(verdicts, indep_traj, dep_traj)

    n_flagged = sum(t["not_supported_count"] + t["needs_broader_context_count"] for t in trajs)
    n_claims = sum(t["not_supported_count"] + t["needs_broader_context_count"]
                   + t["supported_count"] for t in trajs)
    out_stem = ui["out_name"].replace(".html", "")
    html = (HTML
            .replace("__TITLE__", ui["title"])
            .replace("__STORAGE_KEY__", f"binary_review_{args.author_model}")
            .replace("__OUTSTEM__", out_stem)
            .replace("__DATA__", json.dumps(trajs, ensure_ascii=False)))
    out_path.write_text(html, encoding="utf-8")

    print(f"Author: {args.author_model}")
    print(f"Trajectories: {len(trajs)}   claims: {n_claims}   flagged (NS/NBC): {n_flagged}")
    print(f"Wrote {out_path}  ({out_path.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
