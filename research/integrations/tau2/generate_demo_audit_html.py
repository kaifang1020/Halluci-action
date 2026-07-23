"""Generate a standalone HTML report for the Tau2 contract audit demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "fixtures" / "airline_task3_demo_audit.json"
DEFAULT_OUT = HERE / "airline_task3_demo_audit.html"


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Halluci-Action × Tau2 · Airline Task 3 Audit</title>
  <style>
    :root {
      --bg: #f3f6f3;
      --surface: #ffffff;
      --ink: #172019;
      --muted: #5e6a61;
      --border: #d7ded8;
      --border-strong: #b9c4bb;
      --green: #1f774b;
      --green-soft: #e7f4ec;
      --amber: #8a6200;
      --amber-soft: #fff5d6;
      --red: #b42318;
      --red-soft: #feeceb;
      --tool: #3d5543;
      --tool-soft: #edf2ed;
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 14px;
      line-height: 1.55;
    }
    button, a { font: inherit; }
    a { color: var(--green); }
    code, pre, .mono {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    }
    .shell { width: min(1220px, calc(100% - 32px)); margin: 0 auto; }

    .topbar {
      background: #1d2820;
      color: #f7faf7;
      border-bottom: 1px solid #111a14;
    }
    .topbar-inner {
      min-height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }
    .brand { display: flex; align-items: baseline; gap: 10px; }
    .brand strong { font-size: 15px; font-weight: 700; }
    .brand span { color: #b9c8bc; font-size: 12px; }
    .print-button {
      border: 1px solid #647369;
      background: transparent;
      color: #f7faf7;
      border-radius: 5px;
      padding: 7px 12px;
      cursor: pointer;
    }
    .print-button:hover { background: #2b382e; }

    header.report-header { padding: 32px 0 20px; }
    .eyebrow {
      color: var(--green);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    h1 { margin: 5px 0 5px; font-size: 30px; line-height: 1.2; font-weight: 720; }
    .subtitle { color: var(--muted); font-size: 15px; }
    .header-meta {
      margin-top: 18px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .chip {
      border: 1px solid var(--border);
      background: var(--surface);
      border-radius: 999px;
      padding: 4px 9px;
      color: var(--muted);
      font-size: 12px;
    }
    .chip.good { background: var(--green-soft); border-color: #bbddc9; color: #155d39; }
    .chip.warn { background: var(--amber-soft); border-color: #ead795; color: #6c4c00; }

    .notice {
      border: 1px solid #ead795;
      border-left: 4px solid var(--amber);
      background: var(--amber-soft);
      padding: 12px 14px;
      border-radius: 5px;
      color: #5e4505;
      margin-bottom: 18px;
    }
    .notice strong { color: #463302; }

    .metric-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }
    .metric {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 16px;
      min-height: 118px;
    }
    .metric-label { color: var(--muted); font-size: 12px; font-weight: 650; }
    .metric-value { margin-top: 7px; font-size: 30px; line-height: 1; font-weight: 740; }
    .metric-value.good { color: var(--green); }
    .metric-note { margin-top: 9px; color: var(--muted); font-size: 12px; }
    .bar { height: 5px; margin-top: 13px; background: #e6ebe7; border-radius: 3px; overflow: hidden; }
    .bar span { display: block; height: 100%; background: var(--green); }

    .tabs-wrap {
      position: sticky;
      top: 0;
      z-index: 10;
      background: var(--bg);
      padding-top: 8px;
    }
    .tabs {
      display: flex;
      gap: 4px;
      border-bottom: 1px solid var(--border-strong);
      overflow-x: auto;
    }
    .tab-button {
      border: 0;
      border-bottom: 3px solid transparent;
      background: transparent;
      color: var(--muted);
      padding: 10px 14px 9px;
      white-space: nowrap;
      cursor: pointer;
      font-weight: 650;
    }
    .tab-button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--green); }
    .tab-panel { display: none; padding: 20px 0 42px; }
    .tab-panel.active { display: block; }

    .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      margin-bottom: 14px;
    }
    .panel-header {
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }
    .panel-header h2, .panel-header h3 { margin: 0; font-size: 15px; }
    .panel-body { padding: 16px; }
    .task-text { margin: 0; font-size: 15px; max-width: 940px; }
    .muted { color: var(--muted); }

    .direction-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .direction-score { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
    .direction-score strong { font-size: 25px; color: var(--green); }
    .direction-score span { color: var(--muted); }
    .direction-list { margin: 10px 0 0; padding: 0; list-style: none; }
    .direction-list li { padding: 6px 0; border-top: 1px solid #edf0ed; }
    .direction-list li:first-child { border-top: 0; }

    .audit-row {
      display: grid;
      grid-template-columns: 56px minmax(260px, 1.25fr) 92px minmax(240px, 1fr);
      gap: 12px;
      align-items: start;
      padding: 15px 16px;
      border-top: 1px solid var(--border);
    }
    .audit-row:first-child { border-top: 0; }
    .node-id { font-weight: 750; color: var(--green); }
    .node-meta { color: var(--muted); font-size: 11px; margin-top: 2px; }
    .claim-text { font-size: 14px; font-weight: 620; }
    .target { margin-top: 7px; color: var(--muted); font-size: 12px; }
    .edge {
      text-align: center;
      color: var(--green);
      font-size: 12px;
      font-weight: 700;
      padding-top: 3px;
    }
    .action-block code { color: var(--ink); font-size: 12px; word-break: break-word; }
    .evidence { margin-top: 7px; color: var(--muted); font-size: 12px; }
    .badge {
      display: inline-block;
      border-radius: 999px;
      padding: 2px 7px;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
    }
    .badge.good { background: var(--green-soft); color: #155d39; }
    .badge.neutral { background: var(--tool-soft); color: var(--tool); }
    .badge.warn { background: var(--amber-soft); color: #6c4c00; }

    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
    th { background: #f7f9f7; color: var(--muted); font-size: 11px; font-weight: 700; }
    tr:last-child td { border-bottom: 0; }
    td code { font-size: 12px; word-break: break-word; }

    .timeline { position: relative; }
    .timeline::before {
      content: "";
      position: absolute;
      left: 34px;
      top: 16px;
      bottom: 16px;
      width: 1px;
      background: var(--border-strong);
    }
    .turn {
      position: relative;
      display: grid;
      grid-template-columns: 68px minmax(0, 1fr);
      gap: 12px;
      padding: 10px 0;
    }
    .turn-index {
      position: relative;
      z-index: 1;
      width: 68px;
      text-align: center;
    }
    .turn-index span {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 50%;
      border: 1px solid var(--border-strong);
      background: var(--surface);
      font-size: 11px;
      font-weight: 750;
    }
    .turn-content { border: 1px solid var(--border); border-radius: 5px; background: var(--surface); padding: 11px 13px; }
    .turn-role { color: var(--muted); font-size: 11px; font-weight: 750; text-transform: uppercase; }
    .turn-text { margin-top: 4px; }
    .tool-call { margin-top: 8px; background: var(--tool-soft); border: 1px solid var(--border); border-radius: 4px; padding: 7px 9px; font-size: 12px; overflow-x: auto; }
    .refs { margin-top: 8px; display: flex; gap: 5px; flex-wrap: wrap; }

    .contract-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .contract-list { margin: 0; padding-left: 20px; }
    .contract-list li { margin: 7px 0; }
    .key-value { display: grid; grid-template-columns: 170px 1fr; gap: 8px 16px; }
    .key-value dt { color: var(--muted); }
    .key-value dd { margin: 0; }

    footer { border-top: 1px solid var(--border); padding: 18px 0 30px; color: var(--muted); font-size: 12px; }

    @media (max-width: 820px) {
      .metric-grid { grid-template-columns: 1fr 1fr; }
      .direction-grid, .contract-grid { grid-template-columns: 1fr; }
      .audit-row { grid-template-columns: 46px 1fr; }
      .edge { text-align: left; grid-column: 2; padding: 0; }
      .action-block { grid-column: 2; }
      .topbar-inner { min-height: 54px; }
      .brand span { display: none; }
      h1 { font-size: 25px; }
      .key-value { grid-template-columns: 1fr; gap: 2px; }
    }
    @media (max-width: 520px) {
      .shell { width: min(100% - 20px, 1220px); }
      .metric-grid { grid-template-columns: 1fr; }
      .metric { min-height: 100px; }
      header.report-header { padding-top: 24px; }
      .audit-row { padding: 13px 12px; }
      th:nth-child(4), td:nth-child(4) { display: none; }
    }
    @media print {
      body { background: #fff; }
      .topbar, .tabs-wrap, .print-button { display: none !important; }
      .tab-panel { display: block !important; padding: 8px 0 20px; }
      .panel { break-inside: avoid; }
      .shell { width: 100%; }
      a { color: inherit; text-decoration: none; }
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="shell topbar-inner">
      <div class="brand"><strong>Halluci-Action × τ²-bench</strong><span>Bidirectional trajectory audit</span></div>
      <button class="print-button" type="button" onclick="window.print()">打印 / 导出 PDF</button>
    </div>
  </div>

  <main class="shell">
    <header class="report-header">
      <div class="eyebrow">Integration contract demo</div>
      <h1 id="report-title"></h1>
      <div class="subtitle" id="report-subtitle"></div>
      <div class="header-meta" id="header-meta"></div>
    </header>

    <div class="notice" id="method-notice"></div>
    <section class="metric-grid" id="metrics" aria-label="Audit summary"></section>

    <div class="tabs-wrap">
      <nav class="tabs" role="tablist" aria-label="Audit sections">
        <button class="tab-button" role="tab" aria-selected="true" data-tab="overview">结果概览</button>
        <button class="tab-button" role="tab" aria-selected="false" data-tab="evidence">双向证据</button>
        <button class="tab-button" role="tab" aria-selected="false" data-tab="timeline">关键轨迹</button>
        <button class="tab-button" role="tab" aria-selected="false" data-tab="contract">契约说明</button>
      </nav>
    </div>

    <section class="tab-panel active" id="overview" role="tabpanel"></section>
    <section class="tab-panel" id="evidence" role="tabpanel"></section>
    <section class="tab-panel" id="timeline" role="tabpanel"></section>
    <section class="tab-panel" id="contract" role="tabpanel"></section>
  </main>

  <footer><div class="shell">Generated from <span class="mono">halluci_action_demo_audit_v1</span>. Formal severity labels remain out of scope for this demo.</div></footer>

  <script id="audit-data" type="application/json">__REPORT_DATA__</script>
  <script>
    const report = JSON.parse(document.getElementById('audit-data').textContent);
    const esc = (value) => String(value ?? '')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
    const pct = (value) => `${Math.round(Number(value) * 100)}%`;
    const jsonArgs = (args) => Object.entries(args || {})
      .map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(', ');
    const actionById = Object.fromEntries(report.actions.map(action => [action.action_id, action]));

    document.getElementById('report-title').textContent = `${report.title} · ${report.subtitle}`;
    document.getElementById('report-subtitle').textContent = '从多轮对话到 claim–action 双向图的最小接入验证';
    document.getElementById('header-meta').innerHTML = `
      <span class="chip">Task ${esc(report.task_id)}</span>
      <span class="chip">Trajectory ${esc(report.trajectory_id.slice(0, 8))}…</span>
      <span class="chip good">Multi-turn · ${report.interaction.assistant_turns} agent turns</span>
      <span class="chip warn">Manual demo audit</span>`;
    document.getElementById('method-notice').innerHTML = `
      <strong>审计边界：</strong> ${esc(report.methodology.note)}
      Tau2 reference actions are <span class="mono">${esc(report.methodology.reference_binding)}</span>；
      <span class="mono">HAR_severity</span> 暂不计分。`;

    const metricData = [
      ['HAR', report.summary.har.toFixed(2), '普通双向 mismatch rate', 1 - report.summary.har],
      ['Unsupported', `${report.summary.unsupported} / ${report.summary.claim_total}`, 'action-intention / completion claims', report.summary.c2a_score],
      ['Undisclosed', `${report.summary.undisclosed} / ${report.summary.action_total}`, 'executed agent tool actions', report.summary.a2c_score],
      ['Tau2 native reward', report.summary.native_reward.toFixed(2), 'DB × COMMUNICATE', report.summary.native_reward]
    ];
    document.getElementById('metrics').innerHTML = metricData.map(([label, value, note, score]) => `
      <article class="metric">
        <div class="metric-label">${esc(label)}</div>
        <div class="metric-value good">${esc(value)}</div>
        <div class="metric-note">${esc(note)}</div>
        <div class="bar"><span style="width:${pct(score)}"></span></div>
      </article>`).join('');

    document.getElementById('overview').innerHTML = `
      <article class="panel">
        <div class="panel-header"><h2>Visible user request</h2><a href="${esc(report.source_url)}" target="_blank" rel="noreferrer">Tau2 source</a></div>
        <div class="panel-body"><p class="task-text">${esc(report.task)}</p></div>
      </article>
      <div class="direction-grid">
        <article class="panel">
          <div class="panel-header"><h2>Claim → Action</h2><span class="badge good">fully grounded</span></div>
          <div class="panel-body">
            <div class="direction-score"><strong>${pct(report.summary.c2a_score)}</strong><span>C2A alignment</span></div>
            <div class="bar"><span style="width:${pct(report.summary.c2a_score)}"></span></div>
            <ul class="direction-list">
              <li><b>${report.summary.claim_total}</b> auditable action claims</li>
              <li><b>${report.summary.unsupported}</b> unsupported claims</li>
              <li>Target matching: exact or dialogue-context resolved</li>
            </ul>
          </div>
        </article>
        <article class="panel">
          <div class="panel-header"><h2>Action → Claim</h2><span class="badge good">fully disclosed</span></div>
          <div class="panel-body">
            <div class="direction-score"><strong>${pct(report.summary.a2c_score)}</strong><span>A2C alignment</span></div>
            <div class="bar"><span style="width:${pct(report.summary.a2c_score)}"></span></div>
            <ul class="direction-list">
              <li><b>${report.summary.action_total}</b> executed agent actions</li>
              <li><b>${report.summary.undisclosed}</b> undisclosed actions</li>
              <li>User-side actions excluded from the denominator</li>
            </ul>
          </div>
        </article>
      </div>
      <article class="panel">
        <div class="panel-header"><h2>Boundary decision</h2><span class="badge warn">denominator note</span></div>
        <div class="panel-body">
          <p><b>Excluded conditional sentence:</b> “${esc(report.borderline_claim.text)}”</p>
          <p class="muted">${esc(report.borderline_claim.reason_excluded)} ${esc(report.borderline_claim.counterfactual_result)}</p>
        </div>
      </article>`;

    const claimRows = report.claims.map(claim => {
      const actions = claim.action_ids.map(id => actionById[id]);
      return `<div class="audit-row">
        <div><div class="node-id">${esc(claim.claim_id)}</div><div class="node-meta">turn ${claim.turn_idx}</div></div>
        <div>
          <span class="badge neutral">${esc(claim.type)}</span>
          <span class="badge good">${esc(claim.verdict)}</span>
          <div class="claim-text">${esc(claim.text)}</div>
          <div class="target">Target: ${esc(claim.target)} · ${esc(claim.target_match)}</div>
        </div>
        <div class="edge">${esc(claim.relation)} →</div>
        <div class="action-block">
          ${actions.map(action => `<div><b>${esc(action.action_id)}</b> <code>${esc(action.tool_name)}(${esc(jsonArgs(action.parameters))})</code></div>`).join('')}
          <div class="evidence">${esc(claim.evidence)}</div>
        </div>
      </div>`;
    }).join('');

    const actionRows = report.actions.map(action => `
      <tr>
        <td><b>${esc(action.action_id)}</b><div class="node-meta">turn ${action.turn_idx}</div></td>
        <td><code>${esc(action.tool_name)}(${esc(jsonArgs(action.parameters))})</code></td>
        <td><span class="badge good">${esc(action.disclosure)}</span></td>
        <td>${action.matched_claim_ids.map(id => `<span class="badge neutral">${esc(id)}</span>`).join(' ')}</td>
        <td class="muted">${esc(action.result_summary)}</td>
      </tr>`).join('');

    document.getElementById('evidence').innerHTML = `
      <article class="panel">
        <div class="panel-header"><h2>Claim → Action evidence map</h2><span class="muted">${report.claims.length} claim nodes</span></div>
        <div>${claimRows}</div>
      </article>
      <article class="panel">
        <div class="panel-header"><h2>Action → Claim disclosure audit</h2><span class="muted">${report.actions.length} action nodes</span></div>
        <div style="overflow-x:auto"><table>
          <thead><tr><th>Action</th><th>Executed call</th><th>Disclosure</th><th>Matched claims</th><th>Result</th></tr></thead>
          <tbody>${actionRows}</tbody>
        </table></div>
      </article>`;

    const timelineRows = report.timeline.map(turn => `
      <div class="turn">
        <div class="turn-index"><span>${turn.turn_idx}</span></div>
        <div class="turn-content">
          <div class="turn-role">${esc(turn.role)}</div>
          <div class="turn-text">${esc(turn.content)}</div>
          ${turn.tool ? `<div class="tool-call mono">${esc(turn.tool)}</div>` : ''}
          ${(turn.claim_ids || turn.action_ids) ? `<div class="refs">
            ${(turn.claim_ids || []).map(id => `<span class="badge neutral">${esc(id)}</span>`).join('')}
            ${(turn.action_ids || []).map(id => `<span class="badge good">${esc(id)}</span>`).join('')}
          </div>` : ''}
        </div>
      </div>`).join('');
    document.getElementById('timeline').innerHTML = `
      <article class="panel">
        <div class="panel-header"><h2>Key evidence timeline</h2><span class="muted">Tau2 turn_idx preserved</span></div>
        <div class="panel-body timeline">${timelineRows}</div>
      </article>`;

    document.getElementById('contract').innerHTML = `
      <div class="contract-grid">
        <article class="panel">
          <div class="panel-header"><h2>Included in the contract</h2></div>
          <div class="panel-body"><ul class="contract-list">
            <li><code>events</code>: complete user, assistant, and tool chronology</li>
            <li><code>steps</code>: agent-only projection consumed by Pass 1–4</li>
            <li>Tool call IDs, arguments, results, error status, and source turn</li>
            <li>Agent-visible policy separated from evaluator-only task metadata</li>
            <li>Interaction counts for multi-turn / long-horizon stratification</li>
          </ul></div>
        </article>
        <article class="panel">
          <div class="panel-header"><h2>Not claimed by this demo</h2></div>
          <div class="panel-body"><ul class="contract-list">
            <li>No formal Gemini claim extraction or grounding verdict</li>
            <li>No per-action database state delta replay</li>
            <li>No required / forbidden normative labels</li>
            <li>No <code>HAR_severity</code> score</li>
            <li>Tau2 reference actions are not treated as required actions</li>
          </ul></div>
        </article>
      </div>
      <article class="panel">
        <div class="panel-header"><h2>Run metadata</h2></div>
        <div class="panel-body"><dl class="key-value">
          <dt>Schema</dt><dd><code>${esc(report.schema_version)}</code></dd>
          <dt>Trajectory</dt><dd><code>${esc(report.trajectory_id)}</code></dd>
          <dt>Audit mode</dt><dd>${esc(report.methodology.audit_mode)}</dd>
          <dt>Formal judge</dt><dd>${report.methodology.formal_judge_run ? 'run' : 'not run'}</dd>
          <dt>Reference binding</dt><dd><code>${esc(report.methodology.reference_binding)}</code></dd>
          <dt>Severity</dt><dd><code>${esc(report.methodology.severity_status)}</code></dd>
        </dl></div>
      </article>`;

    const activateTab = (tabId, updateHash = true) => {
      const button = document.querySelector(`.tab-button[data-tab="${tabId}"]`);
      const panel = document.getElementById(tabId);
      if (!button || !panel) return;
      document.querySelectorAll('.tab-button').forEach(item => item.setAttribute('aria-selected', 'false'));
      document.querySelectorAll('.tab-panel').forEach(item => item.classList.remove('active'));
      button.setAttribute('aria-selected', 'true');
      panel.classList.add('active');
      if (updateHash) history.replaceState(null, '', `#${tabId}`);
    };
    document.querySelectorAll('.tab-button').forEach(button => {
      button.addEventListener('click', () => activateTab(button.dataset.tab));
    });
    const initialTab = window.location.hash.slice(1);
    if (initialTab) activateTab(initialTab, false);
  </script>
</body>
</html>
"""


def generate_report(data_path: Path, output_path: Path) -> None:
    report = json.loads(data_path.read_text(encoding="utf-8"))
    serialized = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        HTML_TEMPLATE.replace("__REPORT_DATA__", serialized),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    generate_report(args.data, args.out)
    print(f"Wrote audit report: {args.out}")


if __name__ == "__main__":
    main()
