#!/usr/bin/env python3
"""Build a small combined claim/action gap UI for D-5 deepseek chat.

This is intentionally scoped as a concrete visualization prototype:
- claim2action comes from eval_v3-1 stage2 verdicts
- action2claim comes from eval_v3-2 action audit enriched output
- edges are aligned heuristically by sentence id, evidence step, and tool name
"""

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
OUT_HTML = OUT_DIR / "d5_claim_action_gap_ui.html"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
    tool = match.group(1)
    aliases = {
        "get_open_tickets": "search_tickets",
    }
    return aliases.get(tool, tool)


def short_json(value: Any, limit: int = 420) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) > limit:
        return text[:limit] + "\n..."
    return text


def main() -> None:
    a2c_all = load_jsonl(ACTION2CLAIM)
    a2c = [row for row in a2c_all if row.get("traj_key") == "D-5_deepseek"]
    if not a2c:
        raise SystemExit("No action2claim rows found for D-5_deepseek")

    c2a = load_jsonl(CLAIM2ACTION)

    sentences = {s["sentence_id"]: s for s in a2c[0].get("assistant_sentences", [])}
    sentence_by_step: dict[int, list[dict[str, Any]]] = {}
    for sent in sentences.values():
        sentence_by_step.setdefault(int(sent["step_id"]), []).append(sent)

    actions = {row["action_id"]: row for row in a2c}

    # Map claim2action claims to assistant sentence ids when possible.
    c2a_claims: list[dict[str, Any]] = []
    for idx, row in enumerate(c2a):
        step_id = int(row["step_id"])
        claim_norm = norm(row.get("claim_span", ""))
        best_id = None
        best_score = 0
        for sent in sentence_by_step.get(step_id, []):
            sent_norm = norm(sent["text"])
            if not claim_norm or not sent_norm:
                continue
            if claim_norm in sent_norm or sent_norm in claim_norm:
                score = min(len(claim_norm), len(sent_norm))
            else:
                claim_words = set(claim_norm.split())
                sent_words = set(sent_norm.split())
                score = len(claim_words & sent_words)
            if score > best_score:
                best_score = score
                best_id = sent["sentence_id"]
        claim = dict(row)
        claim["claim_local_id"] = f"S{step_id}-C{idx}"
        claim["sentence_id"] = best_id
        c2a_claims.append(claim)

    # Build claim2action edges from evidence pointer -> concrete action.
    c2a_edges: set[tuple[str, str]] = set()
    c2a_edge_rows: list[dict[str, Any]] = []
    for claim in c2a_claims:
        if claim.get("verdict") != "supported" or not claim.get("sentence_id"):
            continue
        evidence = claim.get("evidence_pointer") or {}
        evidence_step = evidence.get("step")
        evidence_tool = tool_from_ref(evidence.get("ref"))
        if evidence_step is None or not evidence_tool:
            continue
        matched = [
            action
            for action in actions.values()
            if int(action["step_id"]) == int(evidence_step)
            and action["tool_name"] == evidence_tool
        ]
        for action in matched:
            edge = (claim["sentence_id"], action["action_id"])
            c2a_edges.add(edge)
            c2a_edge_rows.append(
                {
                    "sentence_id": claim["sentence_id"],
                    "claim": claim,
                    "action": action,
                    "source": "claim2action",
                }
            )

    a2c_edges: set[tuple[str, str]] = set()
    for action in actions.values():
        for sentence_id in action.get("matched_sentence_ids") or []:
            a2c_edges.add((sentence_id, action["action_id"]))

    all_edges = sorted(c2a_edges | a2c_edges, key=lambda x: (x[0], x[1]))
    conflicts = [
        (sid, aid)
        for sid, aid in all_edges
        if ((sid, aid) in c2a_edges) != ((sid, aid) in a2c_edges)
    ]

    action_gaps = [
        action
        for action in actions.values()
        if not action.get("said")
        or action.get("requirement_status") in {"unnecessary", "forbidden"}
    ]
    severe_action_gaps = [
        action
        for action in actions.values()
        if not action.get("said")
        and action.get("requirement_status") in {"unnecessary", "forbidden"}
    ]
    claim_gaps = [
        claim
        for claim in c2a_claims
        if claim.get("verdict") in {"not_supported", "needs_broader_context"}
    ]

    normal_actions = sum(1 for action in actions.values() if action.get("category") == "normal")

    def badge(text: str, cls: str = "") -> str:
        return f'<span class="badge {cls}">{esc(text)}</span>'

    def action_card(action: dict[str, Any]) -> str:
        matched = action.get("matched_sentence_ids") or []
        matched_html = (
            " ".join(badge(sid, "blue") for sid in matched)
            if matched
            else badge("none", "red")
        )
        params = short_json(action.get("parameters", {}))
        final_cls = "red" if action.get("category") == "silent_bad" else "amber"
        return f"""
        <article class="row action-row" data-kind="{esc(action.get('category'))}">
          <div class="idcol">
            <div class="mono">{esc(action['action_id'])}</div>
            <div class="muted">step {esc(action['step_id'])}</div>
          </div>
          <div>
            <div class="title">{esc(action['tool_name'])} {badge(action.get('category'), final_cls)}</div>
            <pre>{esc(params)}</pre>
            <div class="kv"><b>matched claim</b><span>{matched_html}</span></div>
            <div class="kv"><b>requirement</b><span>{badge(action.get('requirement_status'), 'blue' if action.get('R') else 'red')}</span></div>
            <div class="reason">{esc(action.get('said_reason'))}</div>
            <div class="reason">{esc(action.get('requirement_reason'))}</div>
          </div>
        </article>
        """

    def claim_card(claim: dict[str, Any]) -> str:
        sid = claim.get("sentence_id") or "unmapped"
        verdict_cls = "red" if claim.get("verdict") == "not_supported" else "amber"
        return f"""
        <article class="row">
          <div class="idcol">
            <div class="mono">{esc(sid)}</div>
            <div class="muted">step {esc(claim.get('step_id'))}</div>
          </div>
          <div>
            <div class="title">{esc(claim.get('claim_span'))} {badge(claim.get('verdict'), verdict_cls)}</div>
            <div class="kv"><b>type</b><span>{badge(claim.get('claim_type'), 'blue')}</span></div>
            <div class="kv"><b>evidence</b><span>{esc((claim.get('evidence_pointer') or {}).get('ref'))}</span></div>
            <div class="reason">{esc(claim.get('reason'))}</div>
          </div>
        </article>
        """

    def edge_row(sid: str, aid: str) -> str:
        in_c2a = (sid, aid) in c2a_edges
        in_a2c = (sid, aid) in a2c_edges
        action = actions.get(aid, {})
        sentence = sentences.get(sid, {})
        status = "both" if in_c2a and in_a2c else "claim2action only" if in_c2a else "action2claim only"
        cls = "green" if status == "both" else "amber"
        return f"""
        <tr>
          <td><span class="mono">{esc(sid)}</span><div class="muted">{esc(sentence.get('text'))}</div></td>
          <td><span class="mono">{esc(aid)}</span><div class="muted">{esc(action.get('tool_name'))} {esc(action.get('parameters'))}</div></td>
          <td>{badge('yes' if in_c2a else 'no', 'green' if in_c2a else 'red')}</td>
          <td>{badge('yes' if in_a2c else 'no', 'green' if in_a2c else 'red')}</td>
          <td>{badge(status, cls)}</td>
        </tr>
        """

    action_html = "\n".join(action_card(action) for action in action_gaps)
    claim_html = "\n".join(claim_card(claim) for claim in claim_gaps)
    conflict_html = "\n".join(edge_row(sid, aid) for sid, aid in conflicts)
    all_edge_html = "\n".join(edge_row(sid, aid) for sid, aid in all_edges)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>D-5 Claim-Action Gap Review</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #fff;
      --line: #d9dfe7;
      --text: #252a33;
      --muted: #657184;
      --blue: #dcebff;
      --blue-text: #285d9f;
      --red: #ffe1e1;
      --red-text: #a33131;
      --amber: #fff0c7;
      --amber-text: #835900;
      --green: #dff5e8;
      --green-text: #22633b;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 24px 32px 12px; border-bottom: 1px solid var(--line); background: var(--panel); position: sticky; top: 0; z-index: 2; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }}
    .sub {{ color: var(--muted); font-size: 14px; }}
    main {{ padding: 18px 32px 36px; }}
    .cards {{ display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    .metric {{ font-size: 30px; font-weight: 750; line-height: 1; }}
    .label {{ color: var(--muted); margin-top: 8px; font-weight: 650; }}
    .tabs {{ display: flex; gap: 8px; margin: 14px 0; }}
    button {{ border: 1px solid var(--line); background: var(--panel); padding: 9px 12px; border-radius: 7px; font-weight: 700; cursor: pointer; }}
    button.active {{ background: #252a33; color: #fff; border-color: #252a33; }}
    section {{ display: none; }}
    section.active {{ display: block; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    .panel h2 {{ margin: 0; padding: 14px 16px; border-bottom: 1px solid var(--line); font-size: 17px; }}
    .row {{ display: grid; grid-template-columns: 160px 1fr; gap: 16px; padding: 16px; border-bottom: 1px solid var(--line); }}
    .row:last-child {{ border-bottom: 0; }}
    .idcol {{ color: var(--muted); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .muted {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
    .title {{ font-weight: 720; margin-bottom: 8px; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 750; background: #eef1f5; color: var(--muted); margin: 0 3px; }}
    .badge.blue {{ background: var(--blue); color: var(--blue-text); }}
    .badge.red {{ background: var(--red); color: var(--red-text); }}
    .badge.amber {{ background: var(--amber); color: var(--amber-text); }}
    .badge.green {{ background: var(--green); color: var(--green-text); }}
    pre {{ background: #f7f9fc; border: 1px solid var(--line); border-radius: 7px; padding: 10px; overflow: auto; max-height: 180px; }}
    .kv {{ display: grid; grid-template-columns: 130px 1fr; gap: 8px; margin: 6px 0; }}
    .kv b {{ color: var(--muted); }}
    .reason {{ margin-top: 8px; background: #f8fafc; border: 1px solid var(--line); border-radius: 7px; padding: 10px; color: #3d4654; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); padding: 12px; }}
    th {{ background: #f1f3f6; color: var(--muted); }}
    @media (max-width: 900px) {{
      .cards {{ grid-template-columns: 1fr 1fr; }}
      .row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>D-5 Claim-Action Gap Review</h1>
    <div class="sub">deepseek chat · action2claim + claim2action combined prototype · heuristic edge alignment</div>
  </header>
  <main>
    <div class="cards">
      <div class="card"><div class="metric">{len(actions)}</div><div class="label">actions</div></div>
      <div class="card"><div class="metric">{len(c2a_claims)}</div><div class="label">claims</div></div>
      <div class="card"><div class="metric">{len(action_gaps)}</div><div class="label">action gaps</div></div>
      <div class="card"><div class="metric">{len(claim_gaps)}</div><div class="label">claim gaps</div></div>
      <div class="card"><div class="metric">{len(conflicts)}</div><div class="label">direction conflicts</div></div>
    </div>
    <div class="cards">
      <div class="card"><div class="metric">{len(severe_action_gaps)}</div><div class="label">silent + unauthorized</div></div>
      <div class="card"><div class="metric">{sum(1 for a in actions.values() if not a.get('said'))}</div><div class="label">did but not said</div></div>
      <div class="card"><div class="metric">{sum(1 for c in claim_gaps if c.get('verdict') == 'not_supported')}</div><div class="label">said but not done</div></div>
      <div class="card"><div class="metric">{normal_actions}</div><div class="label">normal actions</div></div>
      <div class="card"><div class="metric">{len(all_edges)}</div><div class="label">matched edges</div></div>
    </div>

    <div class="tabs">
      <button class="active" data-tab="actions">做了没说 / bad actions</button>
      <button data-tab="claims">说了没做 claims</button>
      <button data-tab="conflicts">两边不一致</button>
      <button data-tab="edges">all edges</button>
    </div>

    <section id="actions" class="active panel">
      <h2>Action-centered gaps</h2>
      {action_html or '<div class="row"><div></div><div>No action gaps.</div></div>'}
    </section>

    <section id="claims" class="panel">
      <h2>Claim-centered gaps</h2>
      {claim_html or '<div class="row"><div></div><div>No claim gaps.</div></div>'}
    </section>

    <section id="conflicts" class="panel">
      <h2>Direction conflicts</h2>
      <table>
        <thead><tr><th>Claim sentence</th><th>Action</th><th>claim2action</th><th>action2claim</th><th>status</th></tr></thead>
        <tbody>{conflict_html}</tbody>
      </table>
    </section>

    <section id="edges" class="panel">
      <h2>All matched edges</h2>
      <table>
        <thead><tr><th>Claim sentence</th><th>Action</th><th>claim2action</th><th>action2claim</th><th>status</th></tr></thead>
        <tbody>{all_edge_html}</tbody>
      </table>
    </section>
  </main>
  <script>
    document.querySelectorAll('button[data-tab]').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('button[data-tab]').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
      }});
    }});
  </script>
</body>
</html>
"""

    OUT_HTML.write_text(html_doc)
    print(f"Wrote {OUT_HTML}")
    print(
        json.dumps(
            {
                "actions": len(actions),
                "claims": len(c2a_claims),
                "action_gaps": len(action_gaps),
                "severe_action_gaps": len(severe_action_gaps),
                "claim_gaps": len(claim_gaps),
                "direction_conflicts": len(conflicts),
                "all_edges": len(all_edges),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
