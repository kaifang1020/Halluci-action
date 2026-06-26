#!/usr/bin/env python3
"""
Generate a self-contained HTML UI for human re-adjudication of the Stage 2
`needs_broader_context` (NBC) verdicts.

NBC means the judge's *routed* evidence channels were silent, so it punted
instead of deciding supported / not_supported. This tool pulls every NBC case
out of the v2 model runs, attaches the full case-specific evidence from the
rendered prompt (Task Requirement + Atomic Claim + Action Evidence), and emits
one HTML file where a human can label each case supported / unsupported /
unsure (+ a free-text note) and export the labels as JSON.

Usage:
    python generate_nbc_review_ui.py                 # writes nbc_review_ui.html
    python generate_nbc_review_ui.py --out foo.html
    python generate_nbc_review_ui.py --dirs binary_results_deepseek_chat_v2 ...
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Default scope: the clean v2 model set, all judged by gemini-3.1-pro.
# Excludes binary_results_gpt4o_v2 (a contaminated deepseek-judged run, 337
# api_errors — dropped from the analysis) and the older v1 deepseek_reasoner
# dir (superseded by binary_results_deepseek_reasoner_v2, re-judged by gemini).
DEFAULT_DIRS = [
    "binary_results_deepseek_chat_v2",
    "binary_results_deepseek_reasoner_v2",
    "binary_results_gemini_flash_v2",
    "binary_results_gpt4o_mini_v2",
    "binary_results_qwen_v2",
]

# The rendered prompt is a big static guideline followed by the case-specific
# tail. Everything the human needs starts at the task-anchor header — named
# "## Task Requirement" in the v2 prompts and "## Task Header" in the older
# deepseek_reasoner snapshot.
_CASE_START = re.compile(r"^## Task (?:Requirement|Header)\b", re.M)
# Drop the trailing judge instruction so the human sees only the evidence.
_CASE_END = re.compile(r"^## Now Verify\b", re.M)


def _model_name(result_dir: str) -> str:
    return result_dir.replace("binary_results_", "").replace("_v2", "")


# Stage-1 judge outputs live as a sibling package; each author has its own
# results_<author>/<split>/<stem>_judge.json with the full per-step claim list.
STAGE1_ROOT = HERE.parent / "stage1"

# claim_id suffix encodes step + within-step claim index, e.g. "...__S8-C16".
_CLAIM_IDX_RE = re.compile(r"__S(\d+)-C(\d+)$")

# Transition phrases that Stage 1 tends to over-extract as action_intention but
# are really conversational filler (no tool action to verify) — surfaced as a
# hint, NOT an auto-label. Mirrors the known M-2 "Let me report this to you."
# case flagged in CHANGELOG.md.
_FILLER_RE = re.compile(
    r"^\s*(let me|i(?:'| a)?ll|i will|i'm going to|now|here'?s|let'?s)\b.*"
    r"(inform|tell|let you know|report|summari|update you|share|present|"
    r"walk you|explain|give you|show you|provide)\b",
    re.I,
)


def _claim_idx(claim_id: str) -> tuple[int | None, int | None]:
    m = _CLAIM_IDX_RE.search(claim_id or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _load_same_step_claims(model: str, split: str, stem: str,
                           step_id: int | None, target_idx: int | None) -> list[dict]:
    """Return every Stage-1 claim in the target claim's step, each tagged with
    its index, type, requires_validation, and whether it is the target — so the
    reviewer sees the claims immediately before/after the one being judged."""
    s1 = STAGE1_ROOT / f"results_{model}" / split / f"{stem}_judge.json"
    if step_id is None or not s1.exists():
        return []
    try:
        steps = json.loads(s1.read_text(encoding="utf-8"))
    except Exception:
        return []
    step = next((s for s in steps if s.get("step_id") == step_id), None)
    if not step:
        return []
    out = []
    for i, c in enumerate(step.get("claims", [])):
        out.append({
            "idx": i,
            "span": c.get("span"),
            "type": c.get("type"),
            "requires_validation": c.get("requires_validation"),
            "is_target": (i == target_idx),
        })
    return out


def _filler_hint(span: str | None, claim_type: str | None) -> bool:
    return bool(claim_type == "action_intention" and span and _FILLER_RE.match(span))


# Trajectories live under research/experiments_v2/**/trajectories/*.json. We
# index them once by their internal trajectory_id so each case can pull the
# tool calls in its validation window ("was this intention actually executed?").
EXPERIMENTS_ROOT = STAGE1_ROOT.parent.parent / "experiments_v2"
_TRAJ_INDEX: dict[str, Path] | None = None


def _traj_index() -> dict[str, Path]:
    global _TRAJ_INDEX
    if _TRAJ_INDEX is None:
        _TRAJ_INDEX = {}
        for p in EXPERIMENTS_ROOT.glob("**/trajectories/*.json"):
            try:
                tid = json.loads(p.read_text(encoding="utf-8")).get("trajectory_id")
            except Exception:
                continue
            if tid and tid not in _TRAJ_INDEX:
                _TRAJ_INDEX[tid] = p
    return _TRAJ_INDEX


def _in_scope(step: int, claim_step: int, scope: str | None) -> bool:
    if scope == "same_or_following_steps":
        return step >= claim_step
    if scope == "same_or_previous_steps":
        return step <= claim_step
    if scope == "previous_steps":
        return step < claim_step
    if scope == "same_step":
        return step == claim_step
    return True  # unknown -> keep all


def _tool_calls_in_scope(traj_id: str, claim_step: int | None,
                         scope: str | None) -> list[dict]:
    """Tool calls within the claim's validation window — so the reviewer can see
    whether an action_intention was actually carried out by a real call."""
    path = _traj_index().get(traj_id)
    if path is None or claim_step is None:
        return []
    try:
        traj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for st in traj.get("steps", []):
        sid = st.get("step_id")
        if sid is None or not _in_scope(sid, claim_step, scope):
            continue
        for tc in st.get("tool_calls", []) or []:
            out.append({
                "step": sid,
                "tool": tc.get("tool_name"),
                "params": tc.get("parameters"),
                "same_step": (sid == claim_step),
            })
    return out


def _extract_case_section(prompt_path: Path) -> str:
    """Return the case-specific tail of a rendered prompt (evidence the human
    needs), stripped of the static guideline header and the judge call-to-act."""
    text = prompt_path.read_text(encoding="utf-8")
    m = _CASE_START.search(text)
    body = text[m.start():] if m else text
    e = _CASE_END.search(body)
    if e:
        body = body[: e.start()]
    return body.strip()


def collect_cases(result_dirs: list[str]) -> list[dict]:
    cases: list[dict] = []
    for rd in result_dirs:
        model = _model_name(rd)
        for jsonl in sorted(glob.glob(str(HERE / rd / "*" / "*_verdicts.jsonl"))):
            jp = Path(jsonl)
            split = jp.parent.name                       # dependent | independent
            stem = jp.name.replace("_verdicts.jsonl", "")  # e.g. C1_C5_C-5_gemini-pro_v1
            for line in jp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("verdict") != "needs_broader_context":
                    continue
                claim_id = rec["claim_id"]
                prompt_path = HERE / rd / "prompts" / split / stem / f"{claim_id}.md"
                evidence = (
                    _extract_case_section(prompt_path)
                    if prompt_path.exists()
                    else "(rendered prompt not found: %s)" % prompt_path
                )
                step_id = rec.get("step_id")
                _, target_idx = _claim_idx(claim_id)
                same_step = _load_same_step_claims(model, split, stem, step_id, target_idx)
                scope = rec.get("validation_scope")
                tool_calls = _tool_calls_in_scope(rec.get("traj_id"), step_id, scope)
                cases.append(
                    {
                        "id": f"{model}::{claim_id}",
                        "model": model,
                        "split": split,
                        "stem": stem,
                        "claim_id": claim_id,
                        "traj_id": rec.get("traj_id"),
                        "step_id": step_id,
                        "claim_span": rec.get("claim_span"),
                        "claim_type": rec.get("claim_type"),
                        "validation_scope": rec.get("validation_scope"),
                        "routed_channels": rec.get("routed_channels"),
                        "judge_reason": rec.get("reason"),
                        "evidence": evidence,
                        "same_step_claims": same_step,
                        "tool_calls_in_scope": tool_calls,
                        "filler_hint": _filler_hint(rec.get("claim_span"), rec.get("claim_type")),
                    }
                )
    # Stable, human-friendly order: by model, then split, then stem, then step.
    cases.sort(key=lambda c: (c["model"], c["split"], c["stem"], c["step_id"] or 0))
    return cases


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage 2 — needs_broader_context human review</title>
<style>
  :root {
    --bg:#f5f6f8; --panel:#ffffff; --panel2:#eef1f5; --border:#d4d9e0;
    --text:#1c2330; --muted:#5b6573; --accent:#2563eb;
    --sup:#1a9d54; --uns2:#d23b3b; --unsure:#b8860b;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  header { position:sticky; top:0; z-index:10; background:var(--panel);
           border-bottom:1px solid var(--border); padding:10px 16px;
           display:flex; gap:14px; align-items:center; flex-wrap:wrap;
           box-shadow:0 1px 4px rgba(0,0,0,.05); }
  header h1 { font-size:15px; margin:0; font-weight:600; }
  .stat { color:var(--muted); font-size:12px; }
  .stat b { color:var(--text); }
  .spacer { flex:1; }
  button, select { font:inherit; color:var(--text); background:var(--panel);
           border:1px solid var(--border); border-radius:6px; padding:5px 10px;
           cursor:pointer; }
  button:hover { border-color:var(--accent); }
  .wrap { max-width:1100px; margin:0 auto; padding:16px; }
  .filters { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
             margin-bottom:14px; }
  .card { background:var(--panel); border:1px solid var(--border);
          border-radius:10px; margin-bottom:16px; overflow:hidden;
          box-shadow:0 1px 3px rgba(0,0,0,.04); }
  .card.done { border-color:var(--accent); }
  .chead { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
           padding:10px 14px; background:var(--panel2);
           border-bottom:1px solid var(--border); }
  .tag { font-size:11px; padding:2px 8px; border-radius:999px;
         background:#e3e8ef; color:var(--muted); border:1px solid var(--border); }
  .tag.model { color:#1e40af; background:#dbe6ff; }
  .tag.type  { color:#92500a; background:#ffeccf; }
  .tag.warn  { color:#8a1c1c; background:#ffe0e0; border-color:#f1b4b4; }
  .idx { color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
  .claim { padding:12px 14px; }
  .claim .label { color:var(--muted); font-size:11px; text-transform:uppercase;
                  letter-spacing:.04em; margin-bottom:3px; }
  .claim .text { font-size:15px; font-weight:600; }
  .reason { padding:0 14px 12px; color:#3a4453; }
  .reason .label { color:var(--muted); font-size:11px; text-transform:uppercase;
                   letter-spacing:.04em; margin-bottom:3px; }
  details.evidence { margin:0 14px 12px; border:1px solid var(--border);
                     border-radius:8px; background:#fbfcfd; }
  details.evidence > summary { cursor:pointer; padding:8px 12px; color:var(--muted);
                     user-select:none; }
  details.evidence[open] > summary { color:var(--text);
                     border-bottom:1px solid var(--border); }
  pre.ev { margin:0; padding:12px; max-height:520px; overflow:auto;
           white-space:pre-wrap; word-break:break-word;
           font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; color:#2b3340; }
  /* surrounding claims (same step) */
  .ctx { margin:0 14px 12px; }
  .ctx .label { color:var(--muted); font-size:11px; text-transform:uppercase;
                letter-spacing:.04em; margin-bottom:5px; }
  .clist { border:1px solid var(--border); border-radius:8px; overflow:hidden; }
  .crow { display:flex; gap:8px; padding:5px 10px; border-bottom:1px solid #eef1f5;
          font-size:13px; align-items:baseline; }
  .crow:last-child { border-bottom:none; }
  .crow .ci { color:#9aa3b2; font:11px ui-monospace,monospace; min-width:30px; }
  .crow .ct { color:#6b7385; font-size:10px; min-width:130px; text-transform:uppercase;
              letter-spacing:.02em; }
  .crow .cspan { flex:1; word-break:break-word; }
  .crow.target { background:#fff6da; }
  .crow.target .cspan { font-weight:700; color:#7a5a00; }
  .crow.target .ci::before { content:"➤ "; }
  .crow.novalidate { opacity:.55; }
  .tcl .cspan { font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; color:#2b3340; }
  .tcl .cspan b { color:#0f5fbf; }
  .crow.tnow { background:#eafaf0; }
  .crow.nonecall { color:#a82424; font-style:italic; }
  .controls { display:flex; gap:8px; align-items:center; flex-wrap:wrap;
              padding:12px 14px; border-top:1px solid var(--border); }
  .vbtn { border-width:1px; }
  .vbtn[data-v="supported"].on   { background:var(--sup);   color:#fff; border-color:var(--sup); }
  .vbtn[data-v="unsupported"].on { background:var(--uns2);  color:#fff; border-color:var(--uns2); }
  .vbtn[data-v="unsure"].on      { background:var(--unsure);color:#fff; border-color:var(--unsure); }
  .note { flex:1; min-width:200px; }
  .note input { width:100%; background:#fff; color:var(--text);
                border:1px solid var(--border); border-radius:6px; padding:6px 9px;
                font:inherit; }
  .meta { color:var(--muted); font-size:11px; padding:0 14px 12px;
          font-family:ui-monospace,monospace; word-break:break-all; }
  .hidden { display:none; }
  .pill { padding:2px 9px; border-radius:999px; font-size:11px; }
  .pill.supported  { background:#d6f3e2; color:#0f7a40; }
  .pill.unsupported{ background:#fbdcdc; color:#a82424; }
  .pill.unsure     { background:#fbeec2; color:#8a6500; }
</style>
</head>
<body>
<header>
  <h1>Stage&nbsp;2 · needs_broader_context review</h1>
  <span class="stat"><b id="s-done">0</b>/<b id="s-total">0</b> labeled</span>
  <span class="stat">✔ <b id="s-sup">0</b> sup · ✘ <b id="s-uns">0</b> unsup · ? <b id="s-unsure">0</b> unsure</span>
  <span class="spacer"></span>
  <select id="f-model"><option value="">all models</option></select>
  <select id="f-status">
    <option value="">all</option>
    <option value="todo">unlabeled</option>
    <option value="done">labeled</option>
    <option value="filler">⚠ likely stage-1 filler</option>
  </select>
  <button id="btn-export">Export JSON</button>
  <button id="btn-csv">Export CSV</button>
  <button id="btn-clear" title="clear all labels">Reset</button>
</header>
<div class="wrap">
  <div class="filters">
    <span class="stat">Labels auto-save to this browser (localStorage). Use Export to save a file.</span>
  </div>
  <div id="list"></div>
</div>
<script>
const CASES = __CASES_JSON__;
const STORAGE_KEY = "nbc_review_labels_v1";
let labels = {};
try { labels = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; } catch(e) { labels = {}; }

function save() { localStorage.setItem(STORAGE_KEY, JSON.stringify(labels)); refreshStats(); }

function refreshStats() {
  let sup=0, uns=0, unsure=0, done=0;
  for (const c of CASES) {
    const l = labels[c.id];
    if (l && l.verdict) {
      done++;
      if (l.verdict==="supported") sup++;
      else if (l.verdict==="unsupported") uns++;
      else if (l.verdict==="unsure") unsure++;
    }
  }
  document.getElementById("s-done").textContent = done;
  document.getElementById("s-total").textContent = CASES.length;
  document.getElementById("s-sup").textContent = sup;
  document.getElementById("s-uns").textContent = uns;
  document.getElementById("s-unsure").textContent = unsure;
}

function esc(s){ const d=document.createElement("div"); d.textContent=s==null?"":String(s); return d.innerHTML; }

function render() {
  const list = document.getElementById("list");
  const fModel = document.getElementById("f-model").value;
  const fStatus = document.getElementById("f-status").value;
  list.innerHTML = "";
  let shown = 0;
  CASES.forEach((c, i) => {
    if (fModel && c.model !== fModel) return;
    const l = labels[c.id] || {};
    const isDone = !!l.verdict;
    if (fStatus==="todo" && isDone) return;
    if (fStatus==="done" && !isDone) return;
    if (fStatus==="filler" && !c.filler_hint) return;
    shown++;
    const card = document.createElement("div");
    card.className = "card" + (isDone ? " done" : "");
    // Surrounding claims (same agent message / step), target highlighted.
    const ctxRows = (c.same_step_claims||[]).map(sc => `
      <div class="crow ${sc.is_target?"target":""} ${sc.requires_validation===false?"novalidate":""}">
        <span class="ci">C${sc.idx}</span>
        <span class="ct">${esc(sc.type)}${sc.requires_validation===false?" · skip":""}</span>
        <span class="cspan">${esc(sc.span)}</span>
      </div>`).join("");
    const ctxBlock = (c.same_step_claims && c.same_step_claims.length) ? `
      <div class="ctx">
        <div class="label">Surrounding claims — same agent message (step ${esc(c.step_id)}); ➤ = the one being judged</div>
        <div class="clist">${ctxRows}</div>
      </div>` : "";
    // Tool calls in this claim's validation window — did the intention execute?
    const tcs = c.tool_calls_in_scope || [];
    const tcRows = tcs.map(t => `
      <div class="crow ${t.same_step?"tnow":""}">
        <span class="ci">s${esc(t.step)}</span>
        <span class="cspan"><b>${esc(t.tool)}</b>(${esc(JSON.stringify(t.params))})</span>
      </div>`).join("");
    const tcBlock = `
      <div class="ctx">
        <div class="label">Tool calls in scope (${esc(c.validation_scope)}) — did this action execute?</div>
        ${tcs.length ? `<div class="clist tcl">${tcRows}</div>`
                     : `<div class="clist"><div class="crow nonecall">⌀ no tool call in this claim's window</div></div>`}
      </div>`;
    card.innerHTML = `
      <div class="chead">
        <span class="idx">#${i+1}</span>
        <span class="tag model">${esc(c.model)}</span>
        <span class="tag">${esc(c.split)}</span>
        <span class="tag type">${esc(c.claim_type)}</span>
        <span class="tag">step ${esc(c.step_id)}</span>
        <span class="tag">${esc(c.validation_scope)}</span>
        ${c.filler_hint ? `<span class="tag warn" title="Heuristic: looks like a conversational transition phrase Stage 1 over-extracted — likely not a verifiable action.">⚠ likely stage-1 filler</span>` : ``}
        ${isDone ? `<span class="pill ${l.verdict}">${l.verdict}</span>` : ``}
      </div>
      <div class="claim">
        <div class="label">Claim</div>
        <div class="text">${esc(c.claim_span)}</div>
      </div>
      <div class="reason">
        <div class="label">Why the judge punted (needs_broader_context)</div>
        <div>${esc(c.judge_reason)}</div>
      </div>
      ${ctxBlock}
      ${tcBlock}
      <details class="evidence">
        <summary>Show task requirement &amp; routed evidence</summary>
        <pre class="ev">${esc(c.evidence)}</pre>
      </details>
      <div class="controls">
        <button class="vbtn ${l.verdict==="supported"?"on":""}"   data-v="supported">✔ supported</button>
        <button class="vbtn ${l.verdict==="unsupported"?"on":""}" data-v="unsupported">✘ unsupported</button>
        <button class="vbtn ${l.verdict==="unsure"?"on":""}"      data-v="unsure">? unsure</button>
        <span class="note"><input type="text" placeholder="note (optional)" value="${esc(l.note||"")}"></span>
      </div>
      <div class="meta">${esc(c.claim_id)} · traj ${esc(c.traj_id)} · routed: ${esc((c.routed_channels||[]).join(", "))}</div>
    `;
    card.querySelectorAll(".vbtn").forEach(btn => {
      btn.addEventListener("click", () => {
        const v = btn.dataset.v;
        const cur = labels[c.id] || {};
        cur.verdict = (cur.verdict===v) ? null : v;  // toggle off if same
        cur.ts = new Date().toISOString();
        labels[c.id] = cur;
        save();
        render();
      });
    });
    const inp = card.querySelector(".note input");
    inp.addEventListener("input", () => {
      const cur = labels[c.id] || {};
      cur.note = inp.value;
      labels[c.id] = cur;
      save();
    });
    list.appendChild(card);
  });
  if (shown===0) list.innerHTML = `<p class="stat">No cases match the current filter.</p>`;
}

function download(name, text, type) {
  const blob = new Blob([text], {type});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

document.getElementById("btn-export").addEventListener("click", () => {
  const out = CASES.map(c => ({
    id: c.id, model: c.model, split: c.split, claim_id: c.claim_id,
    traj_id: c.traj_id, step_id: c.step_id, claim_type: c.claim_type,
    claim_span: c.claim_span, judge_reason: c.judge_reason,
    filler_hint: !!c.filler_hint,
    human_verdict: (labels[c.id]||{}).verdict || null,
    human_note: (labels[c.id]||{}).note || "",
    labeled_at: (labels[c.id]||{}).ts || null,
  }));
  download("nbc_human_labels.json", JSON.stringify(out, null, 2), "application/json");
});

document.getElementById("btn-csv").addEventListener("click", () => {
  const cols = ["id","model","split","claim_id","traj_id","step_id","claim_type","claim_span","human_verdict","human_note"];
  const q = s => `"${String(s==null?"":s).replace(/"/g,'""')}"`;
  const rows = [cols.join(",")];
  for (const c of CASES) {
    const l = labels[c.id]||{};
    rows.push([c.id,c.model,c.split,c.claim_id,c.traj_id,c.step_id,c.claim_type,c.claim_span,l.verdict||"",l.note||""].map(q).join(","));
  }
  download("nbc_human_labels.csv", rows.join("\n"), "text/csv");
});

document.getElementById("btn-clear").addEventListener("click", () => {
  if (confirm("Clear ALL labels in this browser? Export first if you want to keep them.")) {
    labels = {}; save(); render();
  }
});

document.getElementById("f-model").addEventListener("change", render);
document.getElementById("f-status").addEventListener("change", render);

// populate model filter
(function(){
  const sel = document.getElementById("f-model");
  [...new Set(CASES.map(c=>c.model))].sort().forEach(m=>{
    const o=document.createElement("option"); o.value=m; o.textContent=m; sel.appendChild(o);
  });
})();

refreshStats();
render();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dirs", nargs="*", default=DEFAULT_DIRS,
                    help="result dirs to scan (default: all binary_results_*_v2)")
    ap.add_argument("--out", default=str(HERE / "nbc_review_ui.html"),
                    help="output HTML path")
    args = ap.parse_args()

    cases = collect_cases(args.dirs)
    payload = json.dumps(cases, ensure_ascii=False)
    out_html = HTML_TEMPLATE.replace("__CASES_JSON__", payload)
    Path(args.out).write_text(out_html, encoding="utf-8")

    by_model: dict[str, int] = {}
    for c in cases:
        by_model[c["model"]] = by_model.get(c["model"], 0) + 1
    print(f"Collected {len(cases)} needs_broader_context cases:")
    for m, n in sorted(by_model.items()):
        print(f"  {m:18s} {n}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
