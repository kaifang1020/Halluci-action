"""
Action-centric review UI for action-coverage mapping.

Layout philosophy:
  Each trajectory's main view = a flat list of ACTIONS.
  For each action: tool call + step + status + the stage2 refs that matched it.
  Assistant text is collapsed by default (click to expand if you want context).

This differs from generate_mapping_ui.py which is step-centric.

  python -m research.eval_v3-1_claim2action.stage3_action_coverage.generate_mapping_ui_v2 \\
      --mapping-dir eval_v3-1_claim2action/stage3_action_coverage/silent_actions_deepseek_chat \\
      --output-html eval_v3-1_claim2action/stage3_action_coverage/action_view_chat.html \\
      --title-suffix "DeepSeek Chat"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESEARCH = SCRIPT_DIR.parent.parent


def load_trajectories(mapping_dir: Path) -> list[dict]:
    trajs = []
    for split in ("independent", "dependent"):
        for mp in sorted((mapping_dir / split).glob("*_mapping.json")):
            try:
                doc = json.loads(mp.read_text())
            except Exception:
                continue
            label = mp.stem.replace("_mapping", "")
            traj_id = doc.get("traj_id")
            step_texts = _try_load_step_texts(traj_id, mapping_dir.name)
            n_mut_silent = sum(1 for a in doc.get("actions", [])
                               if a["is_mutation"] and a["status"] == "silent"
                               and not a.get("is_retry"))
            trajs.append({
                "split": split,
                "label": label,
                "task": doc.get("task", ""),
                "pair": doc.get("pair", ""),
                "traj_id": traj_id,
                "n_actions": doc.get("n_actions", 0),
                "n_covered": doc.get("n_covered", 0),
                "n_silent": doc.get("n_silent", 0),
                "n_mut_silent": n_mut_silent,
                "actions": doc.get("actions", []),
                "step_texts": step_texts,  # dict[int, str]
                "debug_unmatched_refs": doc.get("debug_unmatched_refs", []),
            })
    return trajs


def _try_load_step_texts(traj_id: str | None, mapping_dir_name: str) -> dict[int, str]:
    if not traj_id:
        return {}
    if "chat" in mapping_dir_name:
        roots = [RESEARCH / "experiments_v2" / "real"]
    elif "reasoner" in mapping_dir_name:
        roots = [RESEARCH / "experiments_v2"]
    else:
        roots = [RESEARCH / "experiments_v2", RESEARCH / "experiments_v2" / "real"]
    for root in roots:
        if not root.exists():
            continue
        for tf in root.rglob("trajectories/*.json"):
            try:
                d = json.loads(tf.read_text())
                if d.get("trajectory_id") == traj_id:
                    return {s["step_id"]: s.get("assistant_text", "")
                            for s in d.get("steps", [])}
            except Exception:
                pass
    return {}


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>PAGE_TITLE</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; background: #f5f5f5; }

#app { display: flex; height: 100vh; }
#sidebar { width: 280px; min-width: 200px; background: #1e1e2e; color: #cdd6f4; display: flex; flex-direction: column; overflow: hidden; }
#sidebar-header { padding: 12px 14px; background: #181825; font-weight: bold; font-size: 14px; border-bottom: 1px solid #313244; flex-shrink: 0; }
#filters { padding: 8px 14px; background: #11111b; color: #cdd6f4; border-bottom: 1px solid #313244; font-size: 11px; display: flex; flex-direction: column; gap: 4px; }
#filters label { display: flex; align-items: center; gap: 5px; cursor: pointer; }
#traj-list { flex: 1; overflow-y: auto; }
.traj-item { padding: 9px 14px; cursor: pointer; border-bottom: 1px solid #313244; display: flex; justify-content: space-between; align-items: flex-start; gap: 6px; }
.traj-item:hover { background: #313244; }
.traj-item.active { background: #45475a; }
.traj-label { font-size: 12px; font-weight: 600; }
.traj-split { font-size: 10px; color: #6c7086; margin-top: 2px; }
.traj-counts { display: flex; gap: 3px; flex-shrink: 0; flex-wrap: wrap; align-items: center; max-width: 110px; justify-content: flex-end; }
.badge { font-size: 10px; padding: 1px 5px; border-radius: 9px; font-weight: bold; }
.badge-cov { background: #a6e3a1; color: #1e1e2e; }
.badge-silent { background: #f38ba8; color: #1e1e2e; }
.badge-mut { background: #eba0ac; color: #1e1e2e; }

#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #fff; }
#top-bar { background: #fff; border-bottom: 1px solid #e0e0e0; padding: 12px 18px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
#traj-title { font-weight: bold; font-size: 16px; color: #1e1e2e; }
#traj-summary { font-size: 12px; color: #555; margin-left: auto; }

#content { flex: 1; overflow-y: auto; padding: 18px; background: #fafafa; }

/* The action list — the core of the action-centric view */
.action-row {
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 6px;
    margin-bottom: 14px;
    overflow: hidden;
}
.action-row.silent { border-color: #f5c0c0; }

.action-bar {
    padding: 10px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    background: #f0f4ff;
}
.action-row.silent .action-bar { background: #fff5f5; }

.action-step { font-size: 11px; font-weight: bold; color: #4040cc; background: #dde3ff; padding: 2px 8px; border-radius: 3px; }
.action-row.silent .action-step { color: #c33; background: #ffd5d5; }
.action-id { font-family: monospace; font-size: 10px; color: #888; }
.tool-call { font-family: 'SF Mono', Menlo, monospace; font-size: 13px; flex: 1; min-width: 200px; }
.tool-call .tool-name { font-weight: bold; color: #0277bd; }
.tool-call .params { color: #555; }

.tag { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: bold; }
.tag-cov { background: #a6e3a1; color: #1e1e2e; }
.tag-sil { background: #f38ba8; color: #1e1e2e; }
.tag-mut { background: #fab387; color: #1e1e2e; }
.tag-retry { background: #bac2de; color: #1e1e2e; }
.tag-reason { background: #cba6f7; color: #1e1e2e; }

.refs-section { padding: 8px 14px; background: #fafafa; border-top: 1px solid #eee; }
.refs-header { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; font-weight: bold; }
.ref-item {
    display: flex;
    gap: 10px;
    padding: 8px 10px;
    background: #fff;
    border: 1px solid #eee;
    border-radius: 4px;
    margin-bottom: 6px;
    font-size: 12px;
}
.ref-num {
    font-family: monospace;
    font-size: 11px;
    background: #f0f0f0;
    padding: 2px 7px;
    border-radius: 3px;
    color: #555;
    flex-shrink: 0;
    align-self: flex-start;
    margin-top: 2px;
    font-weight: bold;
}
.ref-body { flex: 1; min-width: 0; }
.ref-text {
    font-family: monospace;
    font-size: 11px;
    color: #0277bd;
    background: #f0f8ff;
    padding: 4px 6px;
    border-radius: 3px;
    margin-bottom: 4px;
    word-break: break-all;
}
.via-claim {
    font-size: 12px;
    color: #444;
    line-height: 1.4;
    display: flex;
    gap: 6px;
    align-items: flex-start;
}
.claim-pill {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 8px;
    background: #dde3ff;
    color: #3a3acc;
    flex-shrink: 0;
    margin-top: 2px;
    font-weight: bold;
}
.claim-pill.action_intention { background: #b3e5fc; color: #0277bd; }
.claim-pill.action_completion { background: #c8e6c9; color: #2e7d32; }
.claim-pill.observation { background: #fff9c4; color: #827717; }
.claim-pill.constraint_or_policy { background: #f8bbd0; color: #c2185b; }
.claim-quote { font-style: italic; color: #333; }
.method-mark { font-size: 10px; color: #c07000; background: #fff4e0; padding: 1px 5px; border-radius: 8px; margin-left: 4px; font-weight: bold; }

.silent-info {
    padding: 12px 14px;
    background: #fff5f5;
    color: #c33;
    font-size: 13px;
    border-top: 1px solid #f5c0c0;
}
.silent-info strong { display: block; margin-bottom: 4px; }
.silent-context {
    margin-top: 8px;
    padding: 8px 10px;
    background: #fff;
    border: 1px solid #eee;
    border-radius: 4px;
    font-size: 12px;
    color: #444;
    white-space: pre-wrap;
    max-height: 140px;
    overflow-y: auto;
}
.silent-context-label { font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 4px; font-weight: bold; }

.step-context-toggle {
    font-size: 11px;
    color: #4040cc;
    background: #ededff;
    padding: 3px 8px;
    border-radius: 3px;
    cursor: pointer;
    border: 1px solid #dde3ff;
    margin-left: auto;
}
.step-context-toggle:hover { background: #dde3ff; }
.step-context-panel {
    padding: 8px 14px;
    background: #f8f9fc;
    border-top: 1px solid #eee;
    font-size: 12px;
    color: #444;
    white-space: pre-wrap;
    max-height: 180px;
    overflow-y: auto;
    display: none;
}
.step-context-panel.open { display: block; }

#empty-state { padding: 60px 30px; color: #aaa; text-align: center; }

#parser-warnings {
    margin-top: 20px;
    border: 1px solid #fab387;
    border-radius: 6px;
    background: #fff8ed;
}
#parser-warnings-header {
    padding: 8px 14px;
    background: #fff4e0;
    color: #c07000;
    font-size: 12px;
    font-weight: bold;
}

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #ccc; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #999; }
</style>
</head>
<body>
<div id="app">
  <div id="sidebar">
    <div id="sidebar-header">
      🔗 SIDEBAR_TITLE
      <div style="font-size:11px;color:#6c7086;font-weight:normal;margin-top:3px;">TRAJS_COUNT trajectories · ACTIONS_COUNT actions · SILENT_COUNT silent</div>
    </div>
    <div id="filters">
      <label><input type="checkbox" id="filter-silent-only" /> Only show trajs with silent</label>
      <label><input type="checkbox" id="filter-mut-only" /> Only mutation silent</label>
    </div>
    <div id="traj-list"></div>
  </div>
  <div id="main">
    <div id="top-bar">
      <span id="traj-title">Select a trajectory</span>
      <span id="traj-summary"></span>
    </div>
    <div id="content">
      <div id="empty-state">Pick a trajectory on the left to view its action ↔ stage2 ref mapping</div>
    </div>
  </div>
</div>

<script>
const TRAJS = /*TRAJS_DATA*/;
let currentIdx = -1;
let filterSilentOnly = false;
let filterMutOnly = false;

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function buildSidebar() {
  const list = document.getElementById('traj-list');
  list.innerHTML = TRAJS.map((t, i) => {
    if (filterSilentOnly && t.n_silent === 0) return '';
    if (filterMutOnly && t.n_mut_silent === 0) return '';
    const covBadge = `<span class="badge badge-cov">${t.n_covered}/${t.n_actions}</span>`;
    const silBadge = t.n_silent ? `<span class="badge badge-silent">${t.n_silent} SIL</span>` : '';
    const mutBadge = t.n_mut_silent ? `<span class="badge badge-mut">${t.n_mut_silent} MUT</span>` : '';
    return `<div class="traj-item" id="ti-${i}" onclick="selectTraj(${i})">
      <div>
        <div class="traj-label">${escHtml(t.label)}</div>
        <div class="traj-split">${escHtml(t.split)}</div>
      </div>
      <div class="traj-counts">${covBadge}${silBadge}${mutBadge}</div>
    </div>`;
  }).join('');
}

function selectTraj(idx) {
  if (currentIdx >= 0) document.getElementById(`ti-${currentIdx}`)?.classList.remove('active');
  currentIdx = idx;
  document.getElementById(`ti-${idx}`)?.classList.add('active');
  renderTraj(TRAJS[idx]);
}

function paramsToCompact(p) {
  if (!p || Object.keys(p).length === 0) return '()';
  const entries = Object.entries(p).map(([k, v]) => {
    let vstr = typeof v === 'string' ? `"${v}"` : JSON.stringify(v);
    if (vstr.length > 50) vstr = vstr.slice(0, 47) + '...';
    return `${k}=${vstr}`;
  });
  return `(${entries.join(', ')})`;
}

function renderTraj(t) {
  document.getElementById('traj-title').textContent = t.label + (t.task ? ` · ${t.task}` : '');
  document.getElementById('traj-summary').textContent =
    `${t.n_actions} actions · ${t.n_covered} covered · ${t.n_silent} silent` +
    (t.n_mut_silent ? ` (${t.n_mut_silent} mutation silent)` : '');

  let html = '';
  for (const a of t.actions) {
    const isSilent = a.status === 'silent';
    html += `<div class="action-row ${isSilent ? 'silent' : ''}">
      <div class="action-bar">
        <span class="action-step">Step ${a.step_id}</span>
        <span class="action-id">${a.action_id}</span>
        <span class="tool-call">
          <span class="tool-name">${escHtml(a.tool_name)}</span><span class="params">${escHtml(paramsToCompact(a.parameters))}</span>
        </span>
        ${a.is_mutation ? '<span class="tag tag-mut">MUTATION</span>' : ''}
        ${isSilent ? '<span class="tag tag-sil">SILENT</span>' : `<span class="tag tag-cov">${a.n_covering_claims} refs</span>`}
        ${a.is_retry ? '<span class="tag tag-retry">retry</span>' : ''}
        ${a.is_reasoning_only ? '<span class="tag tag-reason">reasoning-only</span>' : ''}
        <button class="step-context-toggle" onclick="toggleStep('${a.action_id}')">show step ${a.step_id} text</button>
      </div>
      <div class="step-context-panel" id="step-${a.action_id}">
        <div style="font-size:10px;color:#888;text-transform:uppercase;margin-bottom:4px;font-weight:bold;">Step ${a.step_id} assistant_text</div>
        ${escHtml(t.step_texts[a.step_id] || '(no text)')}
      </div>`;

    if (!isSilent && a.covered_by && a.covered_by.length > 0) {
      html += `<div class="refs-section">
        <div class="refs-header">stage2 refs that matched this action (${a.covered_by.length})</div>`;
      a.covered_by.forEach((c, i) => {
        const ctype = c.claim_type || '';
        const methodMark = c.method !== 'exact' ? `<span class="method-mark">[${escHtml(c.method)}]</span>` : '';
        html += `<div class="ref-item">
          <span class="ref-num">#${i+1}</span>
          <div class="ref-body">
            <div class="ref-text">${escHtml(c.ref || '')} ${methodMark}</div>
            <div class="via-claim">
              <span class="claim-pill ${ctype}">${escHtml(ctype)}</span>
              <span class="claim-quote">"${escHtml(c.claim_span || '')}"</span>
            </div>
          </div>
        </div>`;
      });
      html += `</div>`;
    } else if (isSilent) {
      let reason = 'No stage2 verdict\'s evidence_pointer references this action.';
      if (a.is_retry) reason = 'This tool was already covered earlier in trajectory. The first call had its own claim; this is a retry without an independent verbal commitment.';
      else if (a.is_reasoning_only) reason = 'The enclosing step\'s assistant_text is entirely inside <reasoning>...</reasoning>. Stage1 filters out reasoning content, so no claim was extracted to reference this action.';
      html += `<div class="silent-info">
        <strong>Why silent</strong>
        ${reason}
        <div class="silent-context">
          <div class="silent-context-label">Step ${a.step_id} assistant_text (for context):</div>
          ${escHtml(t.step_texts[a.step_id] || '(no text)')}
        </div>
      </div>`;
    }
    html += `</div>`;
  }

  if (t.debug_unmatched_refs && t.debug_unmatched_refs.length > 0) {
    html += `<div id="parser-warnings">
      <div id="parser-warnings-header">⚠ Parser warnings — ${t.debug_unmatched_refs.length} stage2 ref(s) referenced a tool not present in the named step</div>
      <div style="padding: 8px 14px;">`;
    for (const d of t.debug_unmatched_refs) {
      html += `<div class="ref-item">
        <span class="ref-num" style="background:#fab387;color:#1e1e2e;">!</span>
        <div class="ref-body">
          <div style="font-size:11px;color:#666;">step ${d.step} · ref_tool=<b>${escHtml(d.ref_tool)}</b></div>
          <div class="ref-text" style="background:#fff4e0;color:#c07000;">${escHtml(d.ref || '')}</div>
        </div>
      </div>`;
    }
    html += `</div></div>`;
  }

  document.getElementById('content').innerHTML = html;
}

function toggleStep(aid) {
  const el = document.getElementById('step-' + aid);
  if (el) el.classList.toggle('open');
}

document.getElementById('filter-silent-only').addEventListener('change', e => {
  filterSilentOnly = e.target.checked;
  buildSidebar();
});
document.getElementById('filter-mut-only').addEventListener('change', e => {
  filterMutOnly = e.target.checked;
  buildSidebar();
});

buildSidebar();
</script>
</body>
</html>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mapping-dir", required=True)
    p.add_argument("--output-html", required=True)
    p.add_argument("--title-suffix", default="")
    args = p.parse_args()

    mapping_dir = RESEARCH / args.mapping_dir
    out_html = RESEARCH / args.output_html

    if args.title_suffix:
        page_title = f"Action ↔ Stage2 Ref Mapping — {args.title_suffix}"
        sidebar_title = f"Action Mapping · {args.title_suffix}"
    else:
        page_title = "Action ↔ Stage2 Ref Mapping"
        sidebar_title = "Action Mapping"

    print(f"Loading mappings from {mapping_dir}…")
    trajs = load_trajectories(mapping_dir)
    total_actions = sum(t["n_actions"] for t in trajs)
    total_silent = sum(t["n_silent"] for t in trajs)
    print(f"  {len(trajs)} trajectories, {total_actions} actions, {total_silent} silent")

    data_js = json.dumps(trajs, ensure_ascii=False)
    html = HTML_TEMPLATE.replace("/*TRAJS_DATA*/", data_js)
    html = html.replace("PAGE_TITLE", page_title)
    html = html.replace("SIDEBAR_TITLE", sidebar_title)
    html = html.replace("TRAJS_COUNT", str(len(trajs)))
    html = html.replace("ACTIONS_COUNT", str(total_actions))
    html = html.replace("SILENT_COUNT", str(total_silent))

    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    print(f"Written → {out_html}")


if __name__ == "__main__":
    main()
