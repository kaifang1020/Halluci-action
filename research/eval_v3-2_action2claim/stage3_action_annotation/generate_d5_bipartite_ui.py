#!/usr/bin/env python3
"""Build a D-5 claim/action bipartite graph prototype."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any


RESEARCH = Path(__file__).resolve().parents[2]
OUT_DIR = RESEARCH / "eval_v3-2_action2claim" / "stage3_action_annotation"
ACTION2CLAIM = OUT_DIR / "outputs" / "real_deepseek_action_audit_enriched.jsonl"
CLAIM2ACTION = (
    RESEARCH
    / "eval_v3-1_claim2action"
    / "stage2"
    / "binary_results_deepseek_chat"
    / "independent"
    / "D-5_gemini-pro_v1_verdicts.jsonl"
)
OUT_HTML = OUT_DIR / "d5_bipartite_gap_graph.html"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def norm(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_`\"'.,:;!?()\\[\\]{}-]+", " ", text)
    return re.sub(r"\s+", " ", text.lower()).strip()


def tool_from_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    match = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", ref)
    if not match:
        return None
    aliases = {"get_open_tickets": "search_tickets"}
    return aliases.get(match.group(1), match.group(1))


def short(text: str, n: int = 96) -> str:
    return text if len(text) <= n else text[: n - 1] + "..."


def main() -> None:
    action_rows = [
        row
        for row in load_jsonl(ACTION2CLAIM)
        if row.get("traj_key") == "D-5_deepseek"
    ]
    if not action_rows:
        raise SystemExit("No D-5_deepseek action rows found")

    actions = {row["action_id"]: row for row in action_rows}
    sentences = {s["sentence_id"]: s for s in action_rows[0].get("assistant_sentences", [])}
    sentence_by_step: dict[int, list[dict[str, Any]]] = {}
    for sent in sentences.values():
        sentence_by_step.setdefault(int(sent["step_id"]), []).append(sent)

    claim_rows = load_jsonl(CLAIM2ACTION)
    claims: list[dict[str, Any]] = []
    for idx, claim in enumerate(claim_rows):
        step_id = int(claim["step_id"])
        claim_norm = norm(claim.get("claim_span", ""))
        best_id = None
        best_score = 0
        for sent in sentence_by_step.get(step_id, []):
            sent_norm = norm(sent["text"])
            if claim_norm in sent_norm or sent_norm in claim_norm:
                score = min(len(claim_norm), len(sent_norm))
            else:
                score = len(set(claim_norm.split()) & set(sent_norm.split()))
            if score > best_score:
                best_score = score
                best_id = sent["sentence_id"]
        row = dict(claim)
        row["claim_node_id"] = best_id or f"C{idx}"
        row["claim_local_id"] = f"S{step_id}-C{idx}"
        claims.append(row)

    claim_nodes: dict[str, dict[str, Any]] = {}
    for sid, sent in sentences.items():
        related = [c for c in claims if c["claim_node_id"] == sid]
        claim_nodes[sid] = {
            "id": sid,
            "kind": "claim",
            "step": sent["step_id"],
            "text": sent["text"],
            "claimTypes": sorted({c.get("claim_type") for c in related if c.get("claim_type")}),
            "verdicts": sorted({c.get("verdict") for c in related if c.get("verdict")}),
        }

    action_nodes = {
        aid: {
            "id": aid,
            "kind": "action",
            "step": row["step_id"],
            "text": f"{row['tool_name']}({json.dumps(row.get('parameters', {}), ensure_ascii=False)})",
            "tool": row["tool_name"],
            "category": row.get("category"),
            "said": bool(row.get("said")),
            "requirement": row.get("requirement_status"),
            "saidReason": row.get("said_reason"),
            "requirementReason": row.get("requirement_reason"),
        }
        for aid, row in actions.items()
    }

    c2a_edges: set[tuple[str, str]] = set()
    for claim in claims:
        if claim.get("verdict") != "supported":
            continue
        sid = claim.get("claim_node_id")
        if sid not in claim_nodes:
            continue
        evidence = claim.get("evidence_pointer") or {}
        evidence_step = evidence.get("step")
        evidence_tool = tool_from_ref(evidence.get("ref"))
        if evidence_step is None or not evidence_tool:
            continue
        for action in actions.values():
            if int(action["step_id"]) == int(evidence_step) and action["tool_name"] == evidence_tool:
                c2a_edges.add((sid, action["action_id"]))

    a2c_edges: set[tuple[str, str]] = set()
    for action in actions.values():
        for sid in action.get("matched_sentence_ids") or []:
            if sid in claim_nodes:
                a2c_edges.add((sid, action["action_id"]))

    all_edges = sorted(c2a_edges | a2c_edges)
    edge_rows = []
    for sid, aid in all_edges:
        source = (
            "both"
            if (sid, aid) in c2a_edges and (sid, aid) in a2c_edges
            else "claim2action"
            if (sid, aid) in c2a_edges
            else "action2claim"
        )
        edge_rows.append({"claim": sid, "action": aid, "source": source})

    connected_claims = {e["claim"] for e in edge_rows}
    connected_actions = {e["action"] for e in edge_rows}
    unmatched_claims = [
        node
        for node in claim_nodes.values()
        if node["id"] not in connected_claims
        or any(v in {"not_supported", "needs_broader_context"} for v in node["verdicts"])
    ]
    unmatched_actions = [
        node
        for node in action_nodes.values()
        if node["id"] not in connected_actions
        or node["said"] is False
        or node["requirement"] in {"unnecessary", "forbidden"}
    ]

    data = {
        "claims": list(claim_nodes.values()),
        "actions": list(action_nodes.values()),
        "edges": edge_rows,
        "unmatchedClaims": [n["id"] for n in unmatched_claims],
        "unmatchedActions": [n["id"] for n in unmatched_actions],
        "summary": {
            "claims": len(claim_nodes),
            "actions": len(action_nodes),
            "claim2actionEdges": len(c2a_edges),
            "action2claimEdges": len(a2c_edges),
            "bothEdges": sum(1 for e in edge_rows if e["source"] == "both"),
            "unmatchedClaims": len(unmatched_claims),
            "unmatchedActions": len(unmatched_actions),
        },
    }

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>D-5 Bipartite Claim-Action Graph</title>
  <style>
    :root {{
      --bg: #f7f7f4;
      --panel: #fff;
      --line: #d8d6cd;
      --text: #22252a;
      --muted: #687077;
      --blue: #1f77b4;
      --orange: #d95f02;
      --green: #2a8f5a;
      --amber: #c7972f;
      --red: #c44e52;
      --claim-stroke: #8fb7d7;
      --action-stroke: #e2aa7c;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--text); background: var(--bg); }}
    header {{ background: var(--panel); border-bottom: 1px solid var(--line); padding: 18px 24px 14px; position: sticky; top: 0; z-index: 5; }}
    h1 {{ margin: 0 0 6px; font-size: 22px; letter-spacing: 0; }}
    .sub {{ color: var(--muted); font-size: 13px; }}
    .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; align-items: center; }}
    button {{ border: 1px solid var(--line); background: #fff; border-radius: 7px; padding: 8px 11px; font-weight: 700; cursor: pointer; }}
    button.active {{ background: #2f3a40; color: #fff; border-color: #2f3a40; }}
    input {{ border: 1px solid var(--line); border-radius: 7px; padding: 8px 10px; min-width: 260px; }}
    main {{ padding: 16px 24px 28px; }}
    .cards {{ display: grid; grid-template-columns: repeat(7, minmax(120px, 1fr)); gap: 10px; margin-bottom: 14px; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    .metric {{ font-size: 24px; font-weight: 760; }}
    .label {{ color: var(--muted); font-size: 12px; margin-top: 4px; font-weight: 650; }}
    .graph-shell {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    .legend {{ display: flex; gap: 14px; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 13px; }}
    .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; }}
    .graph-scroll {{ overflow: auto; max-height: calc(100vh - 236px); }}
    svg {{ display: block; min-width: 1180px; background: #fbfbf8; }}
    .node rect {{ fill: #fff; stroke: #cfcac0; stroke-width: 1; rx: 7; }}
    .node.claim rect {{ stroke: var(--claim-stroke); }}
    .node.action rect {{ stroke: var(--action-stroke); }}
    .node.unmatched rect {{ stroke: var(--red); stroke-width: 2; }}
    .node.dim {{ opacity: .18; }}
    .edge {{ fill: none; stroke-width: 2.8; opacity: .62; }}
    .edge.claim2action {{ stroke: var(--blue); stroke-dasharray: 8 5; }}
    .edge.action2claim {{ stroke: var(--orange); stroke-dasharray: 1 6; stroke-linecap: round; stroke-width: 4; opacity: .9; }}
    .edge.both {{ stroke: var(--green); stroke-width: 4; opacity: .75; }}
    .edge.dim {{ opacity: .08; }}
    .edge.focus {{ opacity: 1; stroke-width: 5; }}
    .node.focus rect {{ stroke-width: 3; }}
    text {{ font-size: 12px; fill: var(--text); }}
    .node-id {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-weight: 750; fill: #536172; }}
    .tiny {{ font-size: 11px; fill: var(--muted); }}
    .detail {{ margin-top: 14px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; min-height: 130px; }}
    .panel h2 {{ margin: 0; padding: 12px 14px; border-bottom: 1px solid var(--line); font-size: 15px; }}
    .panel-body {{ padding: 12px 14px; white-space: pre-wrap; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 760; background: #eef1f5; margin: 2px; }}
    .red {{ color: var(--red); }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 1000px) {{
      .cards {{ grid-template-columns: repeat(2, 1fr); }}
      .detail {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<header>
  <h1>D-5 Bipartite Claim-Action Graph</h1>
  <div class="sub">left = assistant claim sentence · right = tool action · edges show which direction produced the match</div>
  <div class="toolbar">
    <button class="active" data-mode="all">All</button>
    <button data-mode="claim2action">claim2action</button>
    <button data-mode="action2claim">action2claim</button>
    <button data-mode="claim2actionOnly">C2A only</button>
    <button data-mode="action2claimOnly">A2C only</button>
    <button data-mode="both">双重匹配</button>
    <button data-mode="unmatched">没有匹配 / gaps</button>
    <input id="search" placeholder="filter node text, tool, id..." />
  </div>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div class="graph-shell">
    <div class="legend">
      <span><i class="dot" style="background:var(--blue)"></i>claim2action edge dashed</span>
      <span><i class="dot" style="background:var(--orange)"></i>action2claim edge dotted</span>
      <span><i class="dot" style="background:var(--green)"></i>both thick</span>
      <span><i class="dot" style="background:var(--red)"></i>unmatched / gap node</span>
      <span class="muted">Click a node to pin its neighborhood; click again to clear.</span>
    </div>
    <div class="graph-scroll">
      <svg id="graph"></svg>
    </div>
  </div>
  <div class="detail">
    <div class="panel">
      <h2>Selected Claim</h2>
      <div class="panel-body" id="claimDetail">Click a claim node.</div>
    </div>
    <div class="panel">
      <h2>Selected Action</h2>
      <div class="panel-body" id="actionDetail">Click an action node.</div>
    </div>
  </div>
</main>
<script>
const DATA = {json.dumps(data, ensure_ascii=False)};
let mode = 'all';
let query = '';
let pinned = null;

const svg = document.getElementById('graph');
const claimDetail = document.getElementById('claimDetail');
const actionDetail = document.getElementById('actionDetail');

function card(label, value) {{
  return `<div class="card"><div class="metric">${{value}}</div><div class="label">${{label}}</div></div>`;
}}

function updateCards() {{
  const s = DATA.summary;
  document.getElementById('cards').innerHTML = [
    card('claims', s.claims),
    card('actions', s.actions),
    card('claim2action edges', s.claim2actionEdges),
    card('action2claim edges', s.action2claimEdges),
    card('both edges', s.bothEdges),
    card('unmatched claims', s.unmatchedClaims),
    card('unmatched actions', s.unmatchedActions),
  ].join('');
}}

function edgeVisible(edge) {{
  if (mode === 'all') return true;
  if (mode === 'both') return edge.source === 'both';
  if (mode === 'claim2action') return edge.source === 'claim2action' || edge.source === 'both';
  if (mode === 'action2claim') return edge.source === 'action2claim' || edge.source === 'both';
  if (mode === 'claim2actionOnly') return edge.source === 'claim2action';
  if (mode === 'action2claimOnly') return edge.source === 'action2claim';
  if (mode === 'unmatched') return false;
  return true;
}}

function nodeMatches(node) {{
  if (!query) return true;
  const hay = `${{node.id}} ${{node.text}} ${{node.tool || ''}} ${{node.category || ''}} ${{node.requirement || ''}}`.toLowerCase();
  return hay.includes(query.toLowerCase());
}}

function visibleSets() {{
  const visibleEdges = DATA.edges.filter(edgeVisible);
  let claimIds = new Set(visibleEdges.map(e => e.claim));
  let actionIds = new Set(visibleEdges.map(e => e.action));
  if (mode === 'all') {{
    claimIds = new Set(DATA.claims.map(n => n.id));
    actionIds = new Set(DATA.actions.map(n => n.id));
  }}
  if (mode === 'unmatched') {{
    claimIds = new Set(DATA.unmatchedClaims);
    actionIds = new Set(DATA.unmatchedActions);
  }}

  let claims = DATA.claims.filter(n => claimIds.has(n.id) && nodeMatches(n));
  let actions = DATA.actions.filter(n => actionIds.has(n.id) && nodeMatches(n));
  const keptClaims = new Set(claims.map(n => n.id));
  const keptActions = new Set(actions.map(n => n.id));
  const edges = visibleEdges.filter(e => keptClaims.has(e.claim) && keptActions.has(e.action));
  return {{claims, actions, edges}};
}}

function wrapText(text, maxChars=46, lines=3) {{
  const words = String(text || '').split(/\\s+/);
  const out = [];
  let line = '';
  for (const word of words) {{
    if ((line + ' ' + word).trim().length > maxChars) {{
      out.push(line.trim());
      line = word;
    }} else {{
      line = (line + ' ' + word).trim();
    }}
    if (out.length >= lines) break;
  }}
  if (line && out.length < lines) out.push(line);
  if (words.join(' ').length > out.join(' ').length) out[out.length - 1] += '...';
  return out;
}}

function draw() {{
  pinned = null;
  const {{claims, actions, edges}} = visibleSets();
  const rowH = 92;
  const top = 34;
  const leftX = 34;
  const rightX = 760;
  const nodeW = 360;
  const nodeH = 68;
  const height = Math.max(claims.length, actions.length, 3) * rowH + top + 30;
  const width = 1180;
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.innerHTML = '';

  const claimPos = new Map();
  const actionPos = new Map();
  claims.forEach((n, i) => claimPos.set(n.id, {{x:leftX, y:top + i*rowH}}));
  actions.forEach((n, i) => actionPos.set(n.id, {{x:rightX, y:top + i*rowH}}));

  const edgeLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  svg.appendChild(edgeLayer);
  edges.forEach(e => {{
    const c = claimPos.get(e.claim);
    const a = actionPos.get(e.action);
    if (!c || !a) return;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const x1 = c.x + nodeW;
    const y1 = c.y + nodeH/2;
    const x2 = a.x;
    const y2 = a.y + nodeH/2;
    const mid = (x1 + x2) / 2;
    path.setAttribute('d', `M ${{x1}} ${{y1}} C ${{mid}} ${{y1}}, ${{mid}} ${{y2}}, ${{x2}} ${{y2}}`);
    path.setAttribute('class', `edge ${{e.source}}`);
    path.setAttribute('data-claim', e.claim);
    path.setAttribute('data-action', e.action);
    edgeLayer.appendChild(path);
  }});

  function addNode(node, pos, side) {{
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    const unmatched = side === 'claim' ? DATA.unmatchedClaims.includes(node.id) : DATA.unmatchedActions.includes(node.id);
    g.setAttribute('class', `node ${{side}} ${{unmatched ? 'unmatched' : ''}}`);
    g.setAttribute('data-node-id', node.id);
    g.setAttribute('data-side', side);
    g.setAttribute('transform', `translate(${{pos.x}},${{pos.y}})`);
    g.style.cursor = 'pointer';
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('width', nodeW);
    rect.setAttribute('height', nodeH);
    g.appendChild(rect);
    const idText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    idText.setAttribute('x', 12);
    idText.setAttribute('y', 20);
    idText.setAttribute('class', 'node-id');
    idText.textContent = node.id;
    g.appendChild(idText);
    const meta = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    meta.setAttribute('x', 118);
    meta.setAttribute('y', 20);
    meta.setAttribute('class', 'tiny');
    meta.textContent = side === 'claim'
      ? `step ${{node.step}} ${{(node.verdicts || []).join(', ')}}`
      : `step ${{node.step}} ${{node.category || ''}}`;
    g.appendChild(meta);
    wrapText(node.text, 50, 2).forEach((line, i) => {{
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', 12);
      t.setAttribute('y', 42 + i*16);
      t.textContent = line;
      g.appendChild(t);
    }});
    g.addEventListener('click', () => {{
      showDetail(node, side);
      if (pinned && pinned.id === node.id && pinned.side === side) {{
        pinned = null;
        clearFocus();
      }} else {{
        pinned = {{id: node.id, side}};
        focusNode(node.id, side);
      }}
    }});
    svg.appendChild(g);
  }}

  claims.forEach(n => addNode(n, claimPos.get(n.id), 'claim'));
  actions.forEach(n => addNode(n, actionPos.get(n.id), 'action'));
}}

function focusNode(nodeId, side) {{
  svg.querySelectorAll('.edge').forEach(edge => {{
    const connected = side === 'claim'
      ? edge.dataset.claim === nodeId
      : edge.dataset.action === nodeId;
    edge.classList.toggle('focus', connected);
    edge.classList.toggle('dim', !connected);
  }});
  svg.querySelectorAll('.node').forEach(node => {{
    const id = node.dataset.nodeId;
    let connected = id === nodeId;
    if (!connected) {{
      for (const edge of svg.querySelectorAll('.edge.focus')) {{
        if (edge.dataset.claim === id || edge.dataset.action === id) {{
          connected = true;
          break;
        }}
      }}
    }}
    node.classList.toggle('focus', connected);
    node.classList.toggle('dim', !connected);
  }});
}}

function clearFocus() {{
  svg.querySelectorAll('.edge').forEach(edge => {{
    edge.classList.remove('focus', 'dim');
  }});
  svg.querySelectorAll('.node').forEach(node => {{
    node.classList.remove('focus', 'dim');
  }});
}}

function showDetail(node, side) {{
  if (side === 'claim') {{
    claimDetail.innerHTML = `<b>${{node.id}}</b> <span class="muted">step ${{node.step}}</span>\\n\\n${{escapeHtml(node.text)}}\\n\\n<span class="badge">${{(node.claimTypes || []).join(', ') || 'sentence'}}</span> <span class="badge">${{(node.verdicts || []).join(', ') || 'no claim2action verdict'}}</span>`;
  }} else {{
    actionDetail.innerHTML = `<b>${{node.id}}</b> <span class="muted">step ${{node.step}}</span>\\n\\n${{escapeHtml(node.text)}}\\n\\n<span class="badge">${{node.category}}</span> <span class="badge">${{node.requirement}}</span>\\n\\n<b>said reason</b>\\n${{escapeHtml(node.saidReason || '')}}\\n\\n<b>requirement reason</b>\\n${{escapeHtml(node.requirementReason || '')}}`;
  }}
}}

function escapeHtml(str) {{
  return String(str || '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
}}

document.querySelectorAll('button[data-mode]').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('button[data-mode]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    mode = btn.dataset.mode;
    draw();
  }});
}});
document.getElementById('search').addEventListener('input', e => {{
  query = e.target.value;
  draw();
}});

updateCards();
draw();
</script>
</body>
</html>
"""

    OUT_HTML.write_text(html_doc)
    print(f"Wrote {OUT_HTML}")
    print(json.dumps(data["summary"], indent=2))


if __name__ == "__main__":
    main()
