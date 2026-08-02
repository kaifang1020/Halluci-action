#!/usr/bin/env python3
"""Build a D-5 filtered claim/action bipartite graph.

This prototype separates claim eligibility from claim/action matching. The graph
only shows stage1 claims that require validation and are action-like
(`action_intention` or `action_completion`), while other verifiable/factual
claims remain inspectable in a side panel.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
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
STAGE1_CLAIMS = (
    RESEARCH
    / "eval_v3-1_claim2action"
    / "stage1"
    / "results_deepseek_chat"
    / "independent"
    / "D-5_gemini-pro_v1_judge.json"
)
OUT_HTML = OUT_DIR / "d5_filtered_bipartite_gap_graph.html"

ELIGIBLE_TYPES = {"action_intention", "action_completion"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def norm(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_`\"'.,:;!?()\[\]{}-]+", " ", text)
    return re.sub(r"\s+", " ", text.lower()).strip()


def tool_from_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    match = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\(|→)", ref)
    if not match:
        return None
    aliases = {"get_open_tickets": "search_tickets"}
    return aliases.get(match.group(1), match.group(1))


def short(text: str, n: int = 105) -> str:
    return text if len(text) <= n else text[: n - 1] + "..."


def load_stage1_claim_index(path: Path) -> dict[tuple[int, str], dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    index: dict[tuple[int, str], dict[str, Any]] = {}
    for step in rows:
        step_id = int(step["step_id"])
        for claim in step.get("claims") or []:
            index[(step_id, norm(claim.get("span", "")))] = claim
    return index


def classify_claim(claim: dict[str, Any]) -> tuple[bool, str]:
    claim_type = claim.get("claim_type")
    requires_validation = claim.get("requires_validation")
    if requires_validation is not True:
        return False, "filtered: stage1 requires_validation is not true"
    if claim_type not in ELIGIBLE_TYPES:
        return False, f"filtered: {claim_type or 'unknown'} is not an action claim"
    return True, "eligible: requires_validation action claim"


def attach_sentence_ids(
    claim_rows: list[dict[str, Any]],
    sentences: dict[str, dict[str, Any]],
    stage1_claims: dict[tuple[int, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    sentence_by_step: dict[int, list[dict[str, Any]]] = {}
    for sent in sentences.values():
        sentence_by_step.setdefault(int(sent["step_id"]), []).append(sent)

    out: list[dict[str, Any]] = []
    for claim in claim_rows:
        step_id = int(claim["step_id"])
        claim_norm = norm(claim.get("claim_span", ""))
        best_id = None
        best_score = 0
        for sent in sentence_by_step.get(step_id, []):
            sent_norm = norm(sent["text"])
            if claim_norm in sent_norm or sent_norm in claim_norm:
                score = min(len(claim_norm), len(sent_norm)) + 1000
            else:
                score = len(set(claim_norm.split()) & set(sent_norm.split()))
            if score > best_score:
                best_score = score
                best_id = sent["sentence_id"]
        row = dict(claim)
        stage1_claim = stage1_claims.get((step_id, claim_norm))
        row["requires_validation"] = (
            stage1_claim.get("requires_validation") if stage1_claim else None
        )
        row["stage1_type"] = stage1_claim.get("type") if stage1_claim else None
        row["sentence_id"] = best_id
        row["eligible"], row["eligibility_reason"] = classify_claim(row)
        out.append(row)
    return out


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
    claims = attach_sentence_ids(
        load_jsonl(CLAIM2ACTION),
        sentences,
        load_stage1_claim_index(STAGE1_CLAIMS),
    )
    eligible_claims = [claim for claim in claims if claim["eligible"]]
    filtered_claims = [claim for claim in claims if not claim["eligible"]]

    claim_nodes = {
        claim["claim_id"]: {
            "id": claim["claim_id"],
            "sentenceId": claim.get("sentence_id"),
            "step": claim.get("step_id"),
            "text": claim.get("claim_span"),
            "type": claim.get("claim_type"),
            "requiresValidation": claim.get("requires_validation"),
            "verdict": claim.get("verdict"),
            "reason": claim.get("reason"),
            "eligibility": claim.get("eligibility_reason"),
            "sentenceText": sentences.get(claim.get("sentence_id"), {}).get("text"),
        }
        for claim in eligible_claims
    }

    action_nodes = {
        aid: {
            "id": aid,
            "step": row.get("step_id"),
            "tool": row.get("tool_name"),
            "text": f"{row.get('tool_name')}({json.dumps(row.get('parameters', {}), ensure_ascii=False)})",
            "parameters": row.get("parameters"),
            "result": row.get("tool_result"),
            "category": row.get("category"),
            "relation": row.get("relation"),
            "said": bool(row.get("said")),
            "requirement": row.get("requirement_status"),
            "matchedSentenceIds": row.get("matched_sentence_ids") or [],
            "saidReason": row.get("said_reason"),
            "requirementReason": row.get("requirement_reason"),
        }
        for aid, row in actions.items()
    }

    c2a_edges: set[tuple[str, str]] = set()
    for claim in eligible_claims:
        if claim.get("verdict") != "supported":
            continue
        evidence = claim.get("evidence_pointer") or {}
        if evidence.get("channel") not in {"tool_calls", "tool_results"}:
            continue
        evidence_step = evidence.get("step")
        evidence_tool = tool_from_ref(evidence.get("ref"))
        if evidence_step is None or not evidence_tool:
            continue
        for action in actions.values():
            if int(action["step_id"]) == int(evidence_step) and action["tool_name"] == evidence_tool:
                c2a_edges.add((claim["claim_id"], action["action_id"]))

    claims_by_sentence: dict[str, list[str]] = {}
    for claim in eligible_claims:
        if claim.get("sentence_id"):
            claims_by_sentence.setdefault(claim["sentence_id"], []).append(claim["claim_id"])

    a2c_edges: set[tuple[str, str]] = set()
    for action in actions.values():
        for sid in action.get("matched_sentence_ids") or []:
            for claim_id in claims_by_sentence.get(sid, []):
                a2c_edges.add((claim_id, action["action_id"]))

    edge_rows = []
    for claim_id, action_id in sorted(c2a_edges | a2c_edges):
        if (claim_id, action_id) in c2a_edges and (claim_id, action_id) in a2c_edges:
            source = "both"
        elif (claim_id, action_id) in c2a_edges:
            source = "claim2action"
        else:
            source = "action2claim"
        edge_rows.append({"claim": claim_id, "action": action_id, "source": source})

    connected_claims = {edge["claim"] for edge in edge_rows}
    connected_actions = {edge["action"] for edge in edge_rows}
    unmatched_claim_ids = [
        claim["claim_id"]
        for claim in eligible_claims
        if claim["claim_id"] not in connected_claims
    ]
    unresolved_claim_ids = [
        claim["claim_id"]
        for claim in eligible_claims
        if claim.get("verdict") != "supported"
    ]
    unmatched_action_ids = [
        action_id
        for action_id, action in action_nodes.items()
        if action_id not in connected_actions
    ]
    problematic_action_ids = [
        action_id
        for action_id, action in action_nodes.items()
        if action.get("category") in {"silent_bad", "late_bad", "disclosed_bad"}
    ]

    filtered_counts = Counter(claim.get("claim_type") or "unknown" for claim in filtered_claims)
    data = {
        "claims": list(claim_nodes.values()),
        "filteredClaims": [
            {
                "id": claim.get("claim_id"),
                "sentenceId": claim.get("sentence_id"),
                "step": claim.get("step_id"),
                "text": claim.get("claim_span"),
                "type": claim.get("claim_type"),
                "requiresValidation": claim.get("requires_validation"),
                "verdict": claim.get("verdict"),
                "eligibility": claim.get("eligibility_reason"),
            }
            for claim in filtered_claims
        ],
        "actions": list(action_nodes.values()),
        "edges": edge_rows,
        "unmatchedClaimIds": unmatched_claim_ids,
        "unresolvedClaimIds": unresolved_claim_ids,
        "unmatchedActionIds": unmatched_action_ids,
        "problematicActionIds": problematic_action_ids,
        "summary": {
            "rawClaims": len(claims),
            "eligibleClaims": len(eligible_claims),
            "filteredClaims": len(filtered_claims),
            "filteredCounts": dict(filtered_counts),
            "actions": len(action_nodes),
            "claim2actionEdges": len(c2a_edges),
            "action2claimEdges": len(a2c_edges),
            "bothEdges": sum(1 for edge in edge_rows if edge["source"] == "both"),
            "unmatchedClaims": len(unmatched_claim_ids),
            "unresolvedEligibleClaims": len(unresolved_claim_ids),
            "unmatchedActions": len(unmatched_action_ids),
            "problematicActions": len(problematic_action_ids),
        },
    }

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>D-5 Filtered Claim-Action Graph</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; background: #f7f6f2; color: #22252a; }}
header {{ position: sticky; top: 0; z-index: 5; background: #fff; border-bottom: 1px solid #d9d6cc; padding: 16px 22px; }}
h1 {{ margin: 0 0 6px; font-size: 22px; letter-spacing: 0; }}
.sub {{ color: #66717f; font-size: 13px; }}
.toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 13px; align-items: center; }}
button {{ border: 1px solid #c9c5b8; background: #fff; border-radius: 7px; padding: 8px 11px; font-weight: 750; cursor: pointer; }}
button.active {{ background: #25313b; color: white; border-color: #25313b; }}
main {{ padding: 16px 22px 28px; }}
.cards {{ display: grid; grid-template-columns: repeat(7, minmax(120px, 1fr)); gap: 10px; margin-bottom: 14px; }}
.card {{ background: #fff; border: 1px solid #d9d6cc; border-radius: 8px; padding: 12px; }}
.metric {{ font-size: 24px; font-weight: 850; }}
.label {{ color: #66717f; font-size: 12px; font-weight: 750; margin-top: 4px; }}
.layout {{ display: grid; grid-template-columns: minmax(760px, 1.45fr) minmax(360px, .55fr); gap: 14px; align-items: start; }}
.panel {{ background: #fff; border: 1px solid #d9d6cc; border-radius: 8px; overflow: hidden; }}
.panel h2 {{ margin: 0; padding: 10px 12px; background: #f0eee8; border-bottom: 1px solid #d9d6cc; font-size: 14px; }}
.panel-body {{ padding: 12px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 12px; color: #66717f; font-size: 12px; padding: 10px 12px; border-bottom: 1px solid #d9d6cc; }}
.swatch {{ display: inline-block; width: 24px; height: 3px; vertical-align: middle; margin-right: 5px; border-radius: 99px; }}
.both {{ background: #2a8f5a; }}
.c2a {{ background: #3569a8; }}
.a2c {{ background: #d87c2c; }}
.bad {{ background: #c44e52; }}
.graph-scroll {{ overflow: auto; max-height: calc(100vh - 286px); background: #fbfaf7; }}
svg {{ display: block; min-width: 1160px; }}
.edge {{ fill: none; opacity: .72; stroke-width: 3; }}
.edge.both {{ stroke: #2a8f5a; stroke-width: 4.5; }}
.edge.claim2action {{ stroke: #3569a8; stroke-dasharray: 8 5; }}
.edge.action2claim {{ stroke: #d87c2c; stroke-dasharray: 1 7; stroke-linecap: round; stroke-width: 4; }}
.edge.dim {{ opacity: .08; }}
.edge.focus {{ opacity: 1; stroke-width: 6; }}
.node rect {{ fill: #fff; stroke: #cfc8b8; rx: 7; }}
.node.claim rect {{ stroke: #8baed1; }}
.node.action rect {{ stroke: #dfa66f; }}
.node.unmatched rect {{ stroke: #c44e52; stroke-width: 2.5; }}
.node.unresolved rect {{ stroke: #8b6fcb; stroke-width: 2.5; }}
.node.problem rect {{ stroke: #9b1d1d; stroke-width: 3; }}
.node.dim {{ opacity: .18; }}
.node.focus rect {{ stroke-width: 3.5; }}
text {{ fill: #22252a; font-size: 12px; }}
.id {{ fill: #596474; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-weight: 850; font-size: 11px; }}
.tiny {{ fill: #66717f; font-size: 11px; }}
.badge {{ display: inline-block; background: #e9f1fb; color: #28527a; border-radius: 999px; padding: 2px 7px; margin: 2px; font-size: 11px; font-weight: 800; }}
.badge.red {{ background: #ffe2e2; color: #9b1d1d; }}
.badge.green {{ background: #dff3e8; color: #1f6d45; }}
.detail {{ white-space: pre-wrap; line-height: 1.45; }}
.list {{ display: grid; gap: 8px; max-height: 440px; overflow: auto; }}
.list-item {{ border: 1px solid #e1ded4; border-radius: 7px; padding: 9px; background: #fff; }}
.list-item.filtered {{ background: #fbfaf7; }}
.muted {{ color: #66717f; }}
@media (max-width: 1100px) {{
  .cards {{ grid-template-columns: repeat(2, 1fr); }}
  .layout {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<header>
  <h1>D-5 filtered bipartite graph</h1>
  <div class="sub">Left side contains only stage1 claims with requires_validation=true and type action_intention/action_completion. Observations are kept out of the action-gap graph.</div>
  <div class="toolbar">
    <button data-filter="all" class="active">All eligible</button>
    <button data-filter="both">Both directions</button>
    <button data-filter="c2a">Claim2Action only</button>
    <button data-filter="a2c">Action2Claim only</button>
    <button data-filter="gaps">Unmatched claims/actions</button>
    <button data-filter="unresolved">Direction disagreement</button>
    <button data-filter="problem">Problem actions</button>
    <button data-filter="filtered">Filtered claims</button>
  </div>
</header>
<main>
  <section class="cards" id="cards"></section>
  <section class="layout">
    <div class="panel">
      <h2>Eligible claim/action graph</h2>
      <div class="legend">
        <span><i class="swatch both"></i>both judges agree</span>
        <span><i class="swatch c2a"></i>claim2action only</span>
        <span><i class="swatch a2c"></i>action2claim only</span>
        <span><i class="swatch bad"></i>unmatched claim/action</span>
      </div>
      <div class="graph-scroll"><svg id="graph"></svg></div>
    </div>
    <div class="panel">
      <h2 id="sideTitle">How to read this</h2>
      <div class="panel-body" id="side"></div>
    </div>
  </section>
</main>
<script>
const DATA = {json.dumps(data, ensure_ascii=False)};
let filter = 'all';
let pinned = null;
const claimById = new Map(DATA.claims.map(x => [x.id, x]));
const actionById = new Map(DATA.actions.map(x => [x.id, x]));
const incident = new Map();
for (const edge of DATA.edges) {{
  if (!incident.has(edge.claim)) incident.set(edge.claim, []);
  if (!incident.has(edge.action)) incident.set(edge.action, []);
  incident.get(edge.claim).push(edge);
  incident.get(edge.action).push(edge);
}}

function esc(s) {{
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}}
function pct(n, d) {{ return d ? (100 * n / d).toFixed(1) + '%' : '0.0%'; }}
function short(s, n=88) {{ s = String(s ?? ''); return s.length <= n ? s : s.slice(0, n - 1) + '…'; }}
function badge(text, cls='') {{ return `<span class="badge ${{cls}}">${{esc(text)}}</span>`; }}

function renderCards() {{
  const s = DATA.summary;
  const cards = [
    [s.rawClaims, 'raw extracted claims'],
    [s.eligibleClaims, `eligible action claims · ${{pct(s.eligibleClaims, s.rawClaims)}}`],
    [s.filteredClaims, `filtered out · ${{pct(s.filteredClaims, s.rawClaims)}}`],
    [s.actions, 'tool actions'],
    [s.bothEdges, 'bidirectional edges'],
    [s.unmatchedClaims, 'unmatched claims'],
    [s.unmatchedActions, 'unmatched actions'],
    [s.unresolvedEligibleClaims, 'direction disagreements'],
    [s.problematicActions, 'problematic actions']
  ];
  document.getElementById('cards').innerHTML = cards.map(([num, label]) => `
    <div class="card"><div class="metric">${{esc(num)}}</div><div class="label">${{esc(label)}}</div></div>
  `).join('');
}}

function edgeVisible(edge) {{
  if (filter === 'all') return true;
  if (filter === 'both') return edge.source === 'both';
  if (filter === 'c2a') return edge.source === 'claim2action';
  if (filter === 'a2c') return edge.source === 'action2claim';
  if (filter === 'gaps') return DATA.unmatchedClaimIds.includes(edge.claim) || DATA.unmatchedActionIds.includes(edge.action);
  if (filter === 'unresolved') return DATA.unresolvedClaimIds.includes(edge.claim);
  if (filter === 'problem') return DATA.problematicActionIds.includes(edge.action);
  return true;
}}
function nodeVisible(node) {{
  if (filter === 'filtered') return false;
  if (filter === 'gaps') return DATA.unmatchedClaimIds.includes(node.id) || DATA.unmatchedActionIds.includes(node.id);
  if (filter === 'unresolved') return DATA.unresolvedClaimIds.includes(node.id) || (incident.get(node.id) || []).some(e => DATA.unresolvedClaimIds.includes(e.claim));
  if (filter === 'problem') return DATA.problematicActionIds.includes(node.id) || (incident.get(node.id) || []).some(e => DATA.problematicActionIds.includes(e.action));
  if (filter === 'both') return (incident.get(node.id) || []).some(e => e.source === 'both');
  if (filter === 'c2a') return (incident.get(node.id) || []).some(e => e.source === 'claim2action');
  if (filter === 'a2c') return (incident.get(node.id) || []).some(e => e.source === 'action2claim');
  return true;
}}

function wrapSvgText(text, maxChars, maxLines=3) {{
  const words = String(text ?? '').split(/\\s+/);
  const lines = [];
  let line = '';
  for (const word of words) {{
    const next = line ? line + ' ' + word : word;
    if (next.length > maxChars && line) {{
      lines.push(line);
      line = word;
      if (lines.length >= maxLines) break;
    }} else {{
      line = next;
    }}
  }}
  if (lines.length < maxLines && line) lines.push(line);
  return lines;
}}

function pathFor(x1, y1, x2, y2, offset=0) {{
  const mid = (x1 + x2) / 2;
  return `M ${{x1}} ${{y1 + offset}} C ${{mid}} ${{y1 + offset}}, ${{mid}} ${{y2 - offset}}, ${{x2}} ${{y2 - offset}}`;
}}

function renderGraph() {{
  const svg = document.getElementById('graph');
  if (filter === 'filtered') {{
    svg.setAttribute('height', 120);
    svg.innerHTML = '<text x="28" y="52" class="tiny">Filtered claims are listed on the right. They are intentionally excluded from the graph.</text>';
    renderFilteredPanel();
    return;
  }}

  const claims = DATA.claims;
  const actions = DATA.actions;
  const rowH = 86;
  const top = 40;
  const leftX = 28, rightX = 740;
  const nodeW = 380, nodeH = 62;
  const height = Math.max(claims.length, actions.length) * rowH + 90;
  svg.setAttribute('height', height);
  svg.setAttribute('viewBox', `0 0 1160 ${{height}}`);

  const cpos = new Map();
  const apos = new Map();
  claims.forEach((c, i) => cpos.set(c.id, {{x: leftX, y: top + i * rowH}}));
  actions.forEach((a, i) => apos.set(a.id, {{x: rightX, y: top + i * rowH}}));

  const focusEdges = pinned ? new Set((incident.get(pinned) || []).map(e => `${{e.claim}}=>${{e.action}}`)) : null;
  const focusNodes = new Set();
  if (pinned) {{
    focusNodes.add(pinned);
    for (const e of incident.get(pinned) || []) {{
      focusNodes.add(e.claim);
      focusNodes.add(e.action);
    }}
  }}

  const edgeSvg = DATA.edges.map((e, idx) => {{
    const cp = cpos.get(e.claim), ap = apos.get(e.action);
    if (!cp || !ap) return '';
    const key = `${{e.claim}}=>${{e.action}}`;
    const dim = (pinned && !focusEdges.has(key)) || !edgeVisible(e);
    const focus = pinned && focusEdges.has(key);
    const offset = (idx % 5 - 2) * 4;
    return `<path class="edge ${{e.source}} ${{dim ? 'dim' : ''}} ${{focus ? 'focus' : ''}}" d="${{pathFor(cp.x + nodeW, cp.y + nodeH/2, ap.x, ap.y + nodeH/2, offset)}}"></path>`;
  }}).join('');

  function renderNode(node, kind) {{
    const pos = kind === 'claim' ? cpos.get(node.id) : apos.get(node.id);
    const unmatched = kind === 'claim' ? DATA.unmatchedClaimIds.includes(node.id) : DATA.unmatchedActionIds.includes(node.id);
    const unresolved = kind === 'claim' && DATA.unresolvedClaimIds.includes(node.id);
    const problem = kind === 'action' && DATA.problematicActionIds.includes(node.id);
    const dim = (pinned && !focusNodes.has(node.id)) || !nodeVisible(node);
    const focus = pinned === node.id || focusNodes.has(node.id);
    const title = kind === 'claim'
      ? `${{node.sentenceId || ''}} · ${{node.type}} · ${{node.verdict}}`
      : `${{node.step ? 'step ' + node.step : ''}} · ${{node.category}} · ${{node.requirement}}`;
    const body = kind === 'claim' ? node.text : node.text;
    const lines = wrapSvgText(body, kind === 'claim' ? 56 : 48, 3);
    const lineSvg = lines.map((line, i) => `<text x="${{pos.x + 12}}" y="${{pos.y + 31 + i * 15}}">${{esc(line)}}</text>`).join('');
    return `<g class="node ${{kind}} ${{unmatched ? 'unmatched' : ''}} ${{unresolved ? 'unresolved' : ''}} ${{problem ? 'problem' : ''}} ${{dim ? 'dim' : ''}} ${{focus ? 'focus' : ''}}" data-id="${{esc(node.id)}}" transform="translate(0 0)">
      <rect x="${{pos.x}}" y="${{pos.y}}" width="${{nodeW}}" height="${{nodeH}}"></rect>
      <text class="id" x="${{pos.x + 12}}" y="${{pos.y + 17}}">${{esc(kind === 'claim' ? short(node.id.split('__').pop(), 28) : node.id)}}</text>
      <text class="tiny" x="${{pos.x + nodeW - 12}}" y="${{pos.y + 17}}" text-anchor="end">${{esc(short(title, 46))}}</text>
      ${{lineSvg}}
    </g>`;
  }}
  svg.innerHTML = `
    <text x="${{leftX}}" y="24" class="id">Eligible claims</text>
    <text x="${{rightX}}" y="24" class="id">Tool actions</text>
    ${{edgeSvg}}
    ${{claims.map(c => renderNode(c, 'claim')).join('')}}
    ${{actions.map(a => renderNode(a, 'action')).join('')}}
  `;
  svg.querySelectorAll('.node').forEach(el => {{
    el.addEventListener('click', () => {{
      const id = el.getAttribute('data-id');
      pinned = pinned === id ? null : id;
      render();
    }});
  }});
  renderSide();
}}

function renderSide() {{
  const title = document.getElementById('sideTitle');
  const side = document.getElementById('side');
  if (!pinned) {{
    title.textContent = 'How to read this';
    side.innerHTML = `
      <div class="detail">Final unmatched uses the union of both directions. First build all claim2action and action2claim edges, then subtract connected nodes from each side.</div>
      <p>${{badge('unmatched claim', 'red')}} claim node not matched by either direction; final said-but-not-done candidate</p>
      <p>${{badge('unmatched action', 'red')}} action node not matched by either direction; final done-but-not-said candidate</p>
      <p>${{badge('direction disagreement')}} diagnostic only: a claim/action may have an edge, but one direction did not support it</p>
      <p>${{badge('filtered claims')}} observations and vague text excluded before matching</p>
    `;
    return;
  }}
  if (claimById.has(pinned)) {{
    const c = claimById.get(pinned);
    title.textContent = 'Selected eligible claim';
    const edges = incident.get(pinned) || [];
    side.innerHTML = `
      <div>${{badge(c.type)}} ${{badge(c.verdict, c.verdict === 'supported' ? 'green' : 'red')}} ${{DATA.unmatchedClaimIds.includes(c.id) ? badge('unmatched', 'red') : ''}} ${{DATA.unresolvedClaimIds.includes(c.id) ? badge('unresolved') : ''}}</div>
      <div class="detail"><b>${{esc(c.id)}}</b>\\n${{esc(c.text)}}\\n\\nSentence: ${{esc(c.sentenceId)}}\\n${{esc(c.sentenceText || '')}}\\n\\nClaim2Action reason:\\n${{esc(c.reason || '')}}</div>
      <h3>Edges</h3>
      <div class="list">${{edges.map(e => `<div class="list-item">${{badge(e.source)}} ${{esc(e.action)}} · ${{esc(actionById.get(e.action)?.tool)}}</div>`).join('') || '<div class="muted">No edges.</div>'}}</div>
    `;
  }} else if (actionById.has(pinned)) {{
    const a = actionById.get(pinned);
    title.textContent = 'Selected action';
    const edges = incident.get(pinned) || [];
    side.innerHTML = `
      <div>${{badge(a.category, DATA.problematicActionIds.includes(a.id) ? 'red' : '')}} ${{badge(a.requirement)}} ${{DATA.unmatchedActionIds.includes(a.id) ? badge('unmatched in filtered graph', 'red') : ''}}</div>
      <div class="detail"><b>${{esc(a.id)}} · ${{esc(a.tool)}}</b>\\n${{esc(JSON.stringify(a.parameters, null, 2))}}\\n\\nAction2Claim relation: ${{esc(a.relation || 'none')}}\\nMatched sentences: ${{esc((a.matchedSentenceIds || []).join(', ') || '(none)')}}\\n\\nSaid reason:\\n${{esc(a.saidReason || '')}}\\n\\nRequirement reason:\\n${{esc(a.requirementReason || '')}}</div>
      <h3>Edges</h3>
      <div class="list">${{edges.map(e => `<div class="list-item">${{badge(e.source)}} ${{esc(e.claim.split('__').pop())}} · ${{esc(short(claimById.get(e.claim)?.text, 90))}}</div>`).join('') || '<div class="muted">No eligible-claim edges.</div>'}}</div>
    `;
  }}
}}

function renderFilteredPanel() {{
  document.getElementById('sideTitle').textContent = 'Filtered out claims';
  const grouped = DATA.filteredClaims;
  document.getElementById('side').innerHTML = `
    <div class="detail">These claims are excluded from the graph, so they no longer create noisy unmatched claim nodes. Counts: ${{esc(JSON.stringify(DATA.summary.filteredCounts))}}</div>
    <div class="list">${{grouped.map(c => `
      <div class="list-item filtered">
        <div>${{badge(c.type)}} ${{badge(c.verdict)}} ${{badge(c.eligibility)}}</div>
        <div class="muted">${{esc(c.id)}} · ${{esc(c.sentenceId || '')}}</div>
        <div>${{esc(c.text)}}</div>
      </div>
    `).join('')}}</div>
  `;
}}

function render() {{
  renderCards();
  renderGraph();
}}

document.querySelectorAll('button[data-filter]').forEach(btn => {{
  btn.addEventListener('click', () => {{
    filter = btn.dataset.filter;
    pinned = null;
    document.querySelectorAll('button[data-filter]').forEach(b => b.classList.toggle('active', b === btn));
    render();
  }});
}});
render();
</script>
</body>
</html>
"""
    OUT_HTML.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {OUT_HTML}")
    print(json.dumps(data["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
