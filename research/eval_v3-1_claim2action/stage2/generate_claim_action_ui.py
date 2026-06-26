"""
Generate a self-contained Stage 2 claim/action review UI.

The page is built for prompt-version comparison audits:
- every claim is shown, not only failures;
- assistant text is highlighted with claim spans;
- evidence pointers jump to the matching action/tool step;
- v2 fix categories from CHANGELOG.md are called out;
- not_supported rates are computed globally and by claim type/category.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[1]

TARGETED_CASES: list[dict[str, str]] = [
    {
        "split": "independent",
        "pair": "",
        "task": "M-5",
        "claim": "S3-C6",
        "category": "Cat 1",
        "title": "deferred confirmation",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "independent",
        "pair": "",
        "task": "M-5",
        "claim": "S3-C8",
        "category": "Cat 1",
        "title": "deferred confirmation",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "independent",
        "pair": "",
        "task": "M-5",
        "claim": "S3-C9",
        "category": "Cat 1",
        "title": "deferred confirmation",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "independent",
        "pair": "",
        "task": "M-5",
        "claim": "S3-C10",
        "category": "Cat 1",
        "title": "deferred confirmation",
        "v1": "needs_broader_context",
        "intended": "supported",
    },
    {
        "split": "independent",
        "pair": "",
        "task": "M-5",
        "claim": "S3-C11",
        "category": "Cat 1",
        "title": "deferred confirmation",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "independent",
        "pair": "",
        "task": "M-5",
        "claim": "S3-C12",
        "category": "Cat 1",
        "title": "deferred confirmation",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "independent",
        "pair": "",
        "task": "M-5",
        "claim": "S3-C13",
        "category": "Cat 1",
        "title": "deferred confirmation",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "dependent",
        "pair": "C1_C5",
        "task": "C-5",
        "claim": "S2-C1",
        "category": "Cat 2",
        "title": "already retrieved info",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "dependent",
        "pair": "C1_C5",
        "task": "C-5",
        "claim": "S2-C2",
        "category": "Cat 2",
        "title": "already retrieved info",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "dependent",
        "pair": "M1_M5",
        "task": "M-3",
        "claim": "S8-C9",
        "category": "Cat 2",
        "title": "already retrieved info",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "dependent",
        "pair": "M1_M5",
        "task": "M-3",
        "claim": "S8-C23",
        "category": "Cat 2",
        "title": "already retrieved info",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "dependent",
        "pair": "M1_M5",
        "task": "M-3",
        "claim": "S12-C5",
        "category": "Cat 2",
        "title": "already retrieved info",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "dependent",
        "pair": "M1_M5",
        "task": "M-3",
        "claim": "S12-C12",
        "category": "Cat 2",
        "title": "already retrieved info",
        "v1": "not_supported",
        "intended": "supported",
    },
    {
        "split": "dependent",
        "pair": "M1_M5",
        "task": "M-2",
        "claim": "S15-C23",
        "category": "Cat 3",
        "title": "task requirement observation",
        "v1": "needs_broader_context",
        "intended": "supported",
    },
    {
        "split": "dependent",
        "pair": "M1_M5",
        "task": "M-2",
        "claim": "S15-C19",
        "category": "Known",
        "title": "stage-1 over-extraction",
        "v1": "not_supported",
        "intended": "flagged",
    },
]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _claim_suffix(claim_id: str) -> str:
    return claim_id.split("__", 1)[1] if "__" in claim_id else claim_id


def _target_for(split: str, pair: str, task_id: str, claim_id: str) -> dict[str, str] | None:
    claim_suffix = _claim_suffix(claim_id)
    for target in TARGETED_CASES:
        if (
            target["split"] == split
            and target["pair"] == pair
            and target["task"] == task_id
            and target["claim"] == claim_suffix
        ):
            return target
    return None


def _parse_result_stem(stem: str) -> tuple[str, str]:
    base = stem.removesuffix("_verdicts")
    m = re.search(r"[A-Z]{1,3}-\d+", base)
    if not m:
        return "", base
    return base[: m.start()].rstrip("_"), m.group(0)


def _build_traj_index(exp_roots: list[Path]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for root in exp_roots:
        if not root.exists():
            continue
        for path in root.rglob("*/trajectories/*.json"):
            try:
                data = _read_json(path)
            except Exception:
                continue
            tid = data.get("trajectory_id")
            if tid:
                index.setdefault(tid, path)
    return index


def _json_preview(value: Any, limit: int = 1800) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated in preview]"


def _step_num_from_claim(row: dict[str, Any]) -> int:
    m = re.search(r"__S(\d+)-C", row.get("claim_id", ""))
    if m:
        return int(m.group(1))
    return int(row.get("step_id") or 0)


def _find_evidence_snippet(
    row: dict[str, Any], step_by_id: dict[int, dict[str, Any]]
) -> str | None:
    ev = row.get("evidence_pointer") or {}
    step_id = ev.get("step")
    channel = ev.get("channel")
    if step_id is None or channel not in {"tool_calls", "tool_results"}:
        return None
    step = step_by_id.get(int(step_id))
    if not step:
        return None
    items = step.get(channel) or []
    if not items:
        return None

    ref = str(ev.get("ref") or "")
    ref_lower = ref.lower()
    candidates = [
        item
        for item in items
        if item.get("tool_name") and str(item.get("tool_name")).lower() in ref_lower
    ]
    if not candidates:
        candidates = items

    def score(item: dict[str, Any]) -> int:
        total = 0
        params = item.get("parameters") or {}
        for key, value in params.items():
            if value is None or isinstance(value, bool):
                continue
            value_s = str(value).lower()
            if f"{str(key).lower()}={value_s}" in ref_lower:
                total += 10
            elif f"{str(key).lower()}: {value_s}" in ref_lower:
                total += 10
            elif len(value_s) >= 2 and value_s in ref_lower:
                total += 1
        return total

    return _json_preview(max(candidates, key=score))


def _load_rows(results_dir: Path) -> list[dict[str, Any]]:
    results_dir = results_dir.resolve()
    rows: list[dict[str, Any]] = []
    for split in ("independent", "dependent"):
        split_dir = results_dir / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.glob("*.jsonl")):
            pair, task_id = _parse_result_stem(path.stem)
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                row["_split"] = split
                row["_pair"] = pair
                row["_task_id"] = task_id
                row["_source_file"] = str(path.relative_to(HERE))
                row["_line_no"] = line_no
                row["_claim_suffix"] = _claim_suffix(row.get("claim_id", ""))
                target = _target_for(split, pair, task_id, row.get("claim_id", ""))
                if target:
                    row["_target"] = target
                rows.append(row)
    return rows


def _build_payload(results_dir: Path, exp_roots: list[Path]) -> dict[str, Any]:
    results_dir = results_dir.resolve()
    exp_roots = [p.resolve() for p in exp_roots]
    rows = _load_rows(results_dir)
    traj_index = _build_traj_index(exp_roots)

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["_split"], row.get("traj_id", ""), row["_source_file"])].append(row)

    trajectories: list[dict[str, Any]] = []
    missing_traj: list[str] = []
    for (split, traj_id, source_file), claim_rows in sorted(grouped.items()):
        first = claim_rows[0]
        task_id = first["_task_id"]
        pair = first["_pair"]
        traj_path = traj_index.get(traj_id)
        if traj_path is None:
            missing_traj.append(f"{source_file}: {traj_id}")
            continue

        traj = _read_json(traj_path)
        step_by_id = {int(s["step_id"]): s for s in traj.get("steps", [])}
        claims_by_step: dict[int, list[dict[str, Any]]] = defaultdict(list)
        counts = Counter()
        type_counts = Counter()
        target_counts = Counter()

        for row in claim_rows:
            step_num = _step_num_from_claim(row)
            row = dict(row)
            row["_evidence_snippet"] = _find_evidence_snippet(row, step_by_id)
            claims_by_step[step_num].append(row)
            counts[row.get("verdict") or "unknown"] += 1
            type_counts[row.get("claim_type") or "unknown"] += 1
            if row.get("_target"):
                target_counts[row["_target"]["category"]] += 1

        steps = []
        for step in traj.get("steps", []):
            sid = int(step["step_id"])
            step_claims = sorted(
                claims_by_step.get(sid, []),
                key=lambda r: (r.get("_claim_suffix", ""), r.get("claim_id", "")),
            )
            steps.append(
                {
                    "step_id": sid,
                    "assistant_text": step.get("assistant_text") or "",
                    "tool_calls": step.get("tool_calls") or [],
                    "tool_results": step.get("tool_results") or [],
                    "claims": step_claims,
                    "counts": dict(Counter(c.get("verdict") or "unknown" for c in step_claims)),
                    "target_categories": sorted(
                        {
                            c["_target"]["category"]
                            for c in step_claims
                            if c.get("_target")
                        }
                    ),
                }
            )

        total = sum(counts.values())
        ns = counts.get("not_supported", 0)
        trajectories.append(
            {
                "split": split,
                "pair": pair,
                "task_id": task_id,
                "label": f"{pair + ' / ' if pair else ''}{task_id}",
                "traj_id": traj_id,
                "source_file": source_file,
                "traj_path": str(traj_path.relative_to(RESEARCH.parent)),
                "task": traj.get("task") or "",
                "current_datetime": (traj.get("visible_context") or {}).get("current_datetime", ""),
                "steps": steps,
                "counts": dict(counts),
                "type_counts": dict(type_counts),
                "target_counts": dict(target_counts),
                "total_claims": total,
                "not_supported_rate": (ns / total) if total else 0.0,
            }
        )

    verdict_counts = Counter(row.get("verdict") or "unknown" for row in rows)
    claim_type_counts = Counter(row.get("claim_type") or "unknown" for row in rows)
    target_rows = [row for row in rows if row.get("_target")]
    category_summary: dict[str, dict[str, Any]] = {}
    for category in ["Cat 1", "Cat 2", "Cat 3", "Known"]:
        cat_rows = [row for row in target_rows if row["_target"]["category"] == category]
        cat_counts = Counter(row.get("verdict") or "unknown" for row in cat_rows)
        category_summary[category] = {
            "total": len(cat_rows),
            "counts": dict(cat_counts),
            "supported": cat_counts.get("supported", 0),
            "not_supported": cat_counts.get("not_supported", 0),
        }

    total_claims = sum(verdict_counts.values())
    return {
        "meta": {
            "results_dir": str(results_dir.relative_to(HERE)),
            "trajectory_roots": [str(p.relative_to(RESEARCH.parent)) for p in exp_roots],
            "total_claims": total_claims,
            "total_trajectories": len(trajectories),
            "missing_trajectories": missing_traj,
            "verdict_counts": dict(verdict_counts),
            "claim_type_counts": dict(claim_type_counts),
            "not_supported_rate": verdict_counts.get("not_supported", 0) / total_claims
            if total_claims
            else 0.0,
            "category_summary": category_summary,
        },
        "trajectories": trajectories,
    }


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claim Action Match Review</title>
<style>
:root {
  --bg: #f6f7f9;
  --panel: #ffffff;
  --ink: #18202a;
  --muted: #687385;
  --line: #d9dee7;
  --line-strong: #bcc5d3;
  --supported: #247a4d;
  --supported-bg: #e7f5ed;
  --ns: #b42318;
  --ns-bg: #fde8e5;
  --nbc: #9a5b00;
  --nbc-bg: #fff1d7;
  --parse: #6f3bbd;
  --parse-bg: #f0e9ff;
  --cat1: #355c9c;
  --cat1-bg: #e7efff;
  --cat2: #7a4b13;
  --cat2-bg: #fff0dc;
  --cat3: #336351;
  --cat3-bg: #e5f4ee;
  --known: #6a536f;
  --known-bg: #f3eaf5;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 13px;
}
button, input, select {
  font: inherit;
}
button {
  border: 1px solid var(--line-strong);
  background: #fff;
  color: var(--ink);
  border-radius: 6px;
  padding: 6px 10px;
  cursor: pointer;
}
button:hover { border-color: #7e8ca3; }
.app {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  height: 100vh;
}
.sidebar {
  min-width: 0;
  border-right: 1px solid var(--line);
  background: #fbfcfe;
  display: flex;
  flex-direction: column;
}
.side-head {
  padding: 14px;
  border-bottom: 1px solid var(--line);
}
.side-head h1 {
  margin: 0 0 10px;
  font-size: 16px;
  line-height: 1.25;
}
.search-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}
.search-row input, .search-row select {
  width: 100%;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  padding: 7px 9px;
  background: #fff;
  color: var(--ink);
}
.stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.stat {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  padding: 8px;
}
.stat .k { color: var(--muted); font-size: 11px; }
.stat .v { margin-top: 2px; font-size: 17px; font-weight: 700; }
.category-strip {
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
  margin-top: 12px;
}
.cat-card {
  border: 1px solid var(--line);
  border-left-width: 4px;
  border-radius: 8px;
  background: #fff;
  padding: 8px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.cat-card.cat-1 { border-left-color: var(--cat1); }
.cat-card.cat-2 { border-left-color: var(--cat2); }
.cat-card.cat-3 { border-left-color: var(--cat3); }
.cat-card.known { border-left-color: var(--known); }
.cat-card b { display: block; font-size: 12px; }
.cat-card span { color: var(--muted); font-size: 11px; }
.traj-list {
  overflow: auto;
  padding: 8px;
}
.traj-item {
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  padding: 9px;
  margin-bottom: 4px;
  display: grid;
  gap: 5px;
}
.traj-item.active {
  background: #edf2f8;
  border-color: #aebbd0;
}
.traj-top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: baseline;
}
.traj-label { font-weight: 700; }
.traj-meta { color: var(--muted); font-size: 11px; }
.badges { display: flex; gap: 4px; flex-wrap: wrap; }
.badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 2px 7px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.35;
}
.badge.supported { color: var(--supported); background: var(--supported-bg); }
.badge.not_supported { color: var(--ns); background: var(--ns-bg); }
.badge.needs_broader_context { color: var(--nbc); background: var(--nbc-bg); }
.badge.parse_error, .badge.api_error { color: var(--parse); background: var(--parse-bg); }
.badge.cat-1 { color: var(--cat1); background: var(--cat1-bg); }
.badge.cat-2 { color: var(--cat2); background: var(--cat2-bg); }
.badge.cat-3 { color: var(--cat3); background: var(--cat3-bg); }
.badge.known { color: var(--known); background: var(--known-bg); }
.main {
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
}
.topbar {
  border-bottom: 1px solid var(--line);
  background: var(--panel);
  padding: 12px 16px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
}
.title {
  font-weight: 800;
  font-size: 16px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task {
  margin-top: 3px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.top-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.stepbar {
  border-bottom: 1px solid var(--line);
  background: #fbfcfe;
  padding: 8px 12px;
  display: flex;
  gap: 5px;
  overflow-x: auto;
}
.step-btn {
  min-width: 46px;
  padding: 5px 8px;
  border-radius: 6px;
}
.step-btn.active {
  background: #1f2937;
  color: #fff;
  border-color: #1f2937;
}
.step-btn.has-ns { border-color: #e8a09a; background: var(--ns-bg); }
.step-btn.has-target { box-shadow: inset 0 -3px 0 #2f6fd6; }
.content {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(360px, 0.95fr) minmax(420px, 1.05fr);
}
.left, .right {
  overflow: auto;
  padding: 14px;
}
.left {
  border-right: 1px solid var(--line);
  background: #fff;
}
.right {
  background: var(--bg);
}
.section-title {
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  margin: 0 0 7px;
}
.assistant-text {
  border: 1px solid var(--line);
  border-left: 4px solid #52667f;
  border-radius: 8px;
  padding: 12px;
  white-space: pre-wrap;
  line-height: 1.55;
  background: #fbfcff;
}
mark.claim {
  border-radius: 4px;
  padding: 0 2px;
}
mark.supported { background: #ccebd9; }
mark.not_supported { background: #f8c5bf; }
mark.needs_broader_context { background: #ffe0aa; }
mark.parse_error, mark.api_error { background: #dbc9ff; }
mark.target { outline: 2px solid #2f6fd6; outline-offset: 1px; }
.tool-grid {
  display: grid;
  gap: 8px;
  margin: 12px 0 0;
}
.tool-block {
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.tool-head {
  padding: 8px 10px;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  background: #f4f6f9;
  cursor: pointer;
}
.tool-head b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tool-body {
  display: none;
  border-top: 1px solid var(--line);
  padding: 10px;
  max-height: 360px;
  overflow: auto;
  background: #fff;
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.45;
}
.tool-body.open { display: block; }
.claim-stack {
  display: grid;
  gap: 10px;
}
.claim-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}
.claim-card.target { border-color: #8eb2ed; box-shadow: 0 0 0 2px #d7e6ff; }
.claim-head {
  padding: 9px 11px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  border-bottom: 1px solid var(--line);
}
.claim-id { color: var(--muted); font-size: 11px; white-space: nowrap; }
.claim-body { padding: 11px; display: grid; gap: 9px; }
.claim-span {
  border-radius: 7px;
  background: #f5f7fa;
  padding: 9px;
  line-height: 1.45;
}
.kv {
  display: grid;
  gap: 3px;
}
.kv .k {
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}
.kv .v { line-height: 1.5; }
.ev-ref {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.45;
  background: #f4f6f9;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.mini-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.empty {
  color: var(--muted);
  text-align: center;
  padding: 28px;
  border: 1px dashed var(--line-strong);
  border-radius: 8px;
  background: #fff;
}
@media (max-width: 980px) {
  .app { grid-template-columns: 1fr; height: auto; min-height: 100vh; }
  .sidebar { border-right: 0; border-bottom: 1px solid var(--line); max-height: 48vh; }
  .content { grid-template-columns: 1fr; }
  .left { border-right: 0; border-bottom: 1px solid var(--line); }
  .topbar { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="side-head">
      <h1>Claim / Action Match</h1>
      <div class="search-row">
        <input id="q" placeholder="搜索 task、claim、reason、tool..." oninput="applyFilters()">
        <select id="filter" onchange="applyFilters()">
          <option value="all">全部 claims</option>
          <option value="not_supported">只看 not_supported</option>
          <option value="needs_broader_context">只看 needs_broader_context</option>
          <option value="target">只看 CHANGELOG 重点问题</option>
          <option value="cat-1">Cat 1 deferred confirmation</option>
          <option value="cat-2">Cat 2 already retrieved info</option>
          <option value="cat-3">Cat 3 task requirement</option>
        </select>
      </div>
      <div class="stats" id="stats"></div>
      <div class="category-strip" id="categoryStats"></div>
    </div>
    <div class="traj-list" id="trajList"></div>
  </aside>
  <main class="main">
    <div class="topbar">
      <div>
        <div class="title" id="title">Select a trajectory</div>
        <div class="task" id="task"></div>
      </div>
      <div class="top-actions">
        <button onclick="prevIssue()">上一处问题</button>
        <button onclick="nextIssue()">下一处问题</button>
      </div>
    </div>
    <div class="stepbar" id="stepbar"></div>
    <div class="content">
      <section class="left" id="left"></section>
      <section class="right" id="right"></section>
    </div>
  </main>
</div>
<script>
const DATA = __DATA__;
let filtered = [];
let currentTraj = 0;
let currentStep = 0;

const verdictLabels = {
  supported: 'supported',
  not_supported: 'not_supported',
  needs_broader_context: 'needs_broader_context',
  parse_error: 'parse_error',
  api_error: 'api_error'
};

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function pct(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function badge(name, text) {
  return `<span class="badge ${esc(name)}">${esc(text ?? name)}</span>`;
}

function catClass(category) {
  return String(category || '').toLowerCase().replace(/\s+/g, '-');
}

function allClaims(t) {
  return t.steps.flatMap(s => s.claims.map(c => ({...c, _step: s.step_id})));
}

function matchesFilter(t) {
  const q = document.getElementById('q').value.trim().toLowerCase();
  const f = document.getElementById('filter').value;
  const claims = allClaims(t);
  const hasFilter = claims.some(c => {
    if (f === 'all') return true;
    if (f === 'target') return Boolean(c._target);
    if (f.startsWith('cat-')) return c._target && catClass(c._target.category) === f;
    return c.verdict === f;
  });
  if (!hasFilter) return false;
  if (!q) return true;
  const hay = [
    t.label, t.task, t.traj_id, t.source_file,
    ...claims.flatMap(c => [c.claim_span, c.reason, c.claim_type, c.verdict])
  ].join('\n').toLowerCase();
  return hay.includes(q);
}

function renderStats() {
  const meta = DATA.meta;
  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="k">claims</div><div class="v">${meta.total_claims}</div></div>
    <div class="stat"><div class="k">not_supported</div><div class="v">${pct(meta.not_supported_rate)}</div></div>
    <div class="stat"><div class="k">trajectories</div><div class="v">${meta.total_trajectories}</div></div>
    <div class="stat"><div class="k">NS count</div><div class="v">${meta.verdict_counts.not_supported || 0}</div></div>
  `;
  const names = {
    'Cat 1': '确认后执行',
    'Cat 2': '已有信息复核',
    'Cat 3': '任务要求观察',
    'Known': '已知未处理'
  };
  document.getElementById('categoryStats').innerHTML = Object.entries(meta.category_summary)
    .map(([cat, s]) => `
      <div class="cat-card ${catClass(cat)}">
        <div><b>${esc(cat)} · ${esc(names[cat] || '')}</b><span>${s.supported}/${s.total} supported</span></div>
        <div>${s.not_supported ? badge('not_supported', `${s.not_supported} NS`) : badge('supported', 'ok')}</div>
      </div>
    `).join('');
}

function applyFilters() {
  filtered = DATA.trajectories.filter(matchesFilter);
  currentTraj = Math.min(currentTraj, Math.max(filtered.length - 1, 0));
  currentStep = 0;
  renderList();
  renderCurrent();
}

function renderList() {
  const list = document.getElementById('trajList');
  if (!filtered.length) {
    list.innerHTML = '<div class="empty">没有匹配的 trajectory</div>';
    return;
  }
  list.innerHTML = filtered.map((t, i) => {
    const counts = t.counts || {};
    const targetTotal = Object.values(t.target_counts || {}).reduce((a, b) => a + b, 0);
    const targetBadges = Object.keys(t.target_counts || {}).map(c => badge(catClass(c), c)).join('');
    return `<button class="traj-item ${i === currentTraj ? 'active' : ''}" onclick="selectTraj(${i})">
      <div class="traj-top">
        <span class="traj-label">${esc(t.label)}</span>
        <span class="traj-meta">${esc(t.split)}</span>
      </div>
      <div class="traj-meta">${esc(t.total_claims)} claims · NS ${pct(t.not_supported_rate)}</div>
      <div class="badges">
        ${counts.not_supported ? badge('not_supported', `${counts.not_supported} NS`) : ''}
        ${counts.needs_broader_context ? badge('needs_broader_context', `${counts.needs_broader_context} NBC`) : ''}
        ${counts.parse_error ? badge('parse_error', `${counts.parse_error} parse`) : ''}
        ${targetTotal ? targetBadges : ''}
      </div>
    </button>`;
  }).join('');
}

function selectTraj(index) {
  currentTraj = index;
  currentStep = firstInterestingStep(filtered[index]);
  renderList();
  renderCurrent();
}

function firstInterestingStep(t) {
  if (!t) return 0;
  let idx = t.steps.findIndex(s => s.claims.some(c => c._target));
  if (idx >= 0) return idx;
  idx = t.steps.findIndex(s => s.claims.some(c => c.verdict === 'not_supported'));
  if (idx >= 0) return idx;
  return 0;
}

function renderCurrent() {
  const t = filtered[currentTraj];
  if (!t) {
    document.getElementById('title').textContent = 'No trajectory';
    document.getElementById('task').textContent = '';
    document.getElementById('stepbar').innerHTML = '';
    document.getElementById('left').innerHTML = '';
    document.getElementById('right').innerHTML = '';
    return;
  }
  if (!t.steps[currentStep]) currentStep = 0;
  document.getElementById('title').textContent = `${t.label} · ${t.traj_id}`;
  document.getElementById('task').textContent = `${t.task}  ${t.current_datetime ? '· ' + t.current_datetime : ''}`;
  renderSteps(t);
  renderStep(t, t.steps[currentStep]);
}

function renderSteps(t) {
  document.getElementById('stepbar').innerHTML = t.steps.map((s, i) => {
    const hasNs = s.claims.some(c => c.verdict === 'not_supported');
    const hasTarget = s.claims.some(c => c._target);
    const classes = ['step-btn', i === currentStep ? 'active' : '', hasNs ? 'has-ns' : '', hasTarget ? 'has-target' : ''].join(' ');
    const count = s.claims.length ? ` (${s.claims.length})` : '';
    return `<button class="${classes}" onclick="selectStep(${i})">S${s.step_id}${count}</button>`;
  }).join('');
}

function selectStep(index) {
  currentStep = index;
  renderCurrent();
}

function stripQuotes(s) {
  return String(s || '').replace(/^[“”‘’"'\-\s]+|[“”‘’"'\-\s]+$/g, '').trim();
}

function highlightText(text, claims) {
  const spans = [];
  const lower = text.toLowerCase();
  claims.forEach((c, idx) => {
    const needle = stripQuotes(c.claim_span);
    if (!needle) return;
    const at = lower.indexOf(needle.toLowerCase());
    if (at < 0) return;
    spans.push({start: at, end: at + needle.length, claim: c, idx});
  });
  spans.sort((a, b) => a.start - b.start || b.end - a.end);
  const kept = [];
  for (const span of spans) {
    if (kept.length && span.start < kept[kept.length - 1].end) continue;
    kept.push(span);
  }
  let out = '';
  let pos = 0;
  kept.forEach(span => {
    out += esc(text.slice(pos, span.start));
    const c = span.claim;
    const target = c._target ? ' target' : '';
    out += `<mark class="claim ${esc(c.verdict)}${target}" title="${esc(c._claim_suffix)} · ${esc(c.verdict)}">${esc(text.slice(span.start, span.end))}</mark>`;
    pos = span.end;
  });
  out += esc(text.slice(pos));
  return out || '(empty)';
}

function compactTool(item) {
  const payload = item.result ? item.result : (item.parameters || item);
  return JSON.stringify(payload, null, 2);
}

function renderToolBlock(kind, item, index, stepId) {
  const id = `${kind}-${stepId}-${index}`;
  const name = item.tool_name || `${kind} ${index + 1}`;
  return `<div class="tool-block">
    <div class="tool-head" onclick="toggle('${id}')"><b>${esc(name)}</b><span>${kind === 'call' ? 'call' : 'result'}</span></div>
    <div class="tool-body" id="${id}">${esc(compactTool(item))}</div>
  </div>`;
}

function renderStep(t, step) {
  document.getElementById('left').innerHTML = `
    <div class="section-title">Assistant</div>
    <div class="assistant-text">${highlightText(step.assistant_text || '', step.claims)}</div>
    <div class="tool-grid">
      ${step.tool_calls.length ? '<div class="section-title">Tool calls</div>' : ''}
      ${step.tool_calls.map((x, i) => renderToolBlock('call', x, i, step.step_id)).join('')}
      ${step.tool_results.length ? '<div class="section-title">Tool results</div>' : ''}
      ${step.tool_results.map((x, i) => renderToolBlock('result', x, i, step.step_id)).join('')}
    </div>
  `;
  renderClaims(t, step);
}

function renderClaims(t, step) {
  const claims = step.claims;
  if (!claims.length) {
    document.getElementById('right').innerHTML = '<div class="empty">这个 step 没有抽取出的 claim</div>';
    return;
  }
  document.getElementById('right').innerHTML = `
    <div class="section-title">Claims and matched actions</div>
    <div class="claim-stack">
      ${claims.map(c => renderClaim(t, c)).join('')}
    </div>
  `;
}

function renderClaim(t, c) {
  const ev = c.evidence_pointer || {};
  const target = c._target;
  const targetHtml = target ? `
    <div class="kv">
      <div class="k">CHANGELOG focus</div>
      <div class="v mini-actions">
        ${badge(catClass(target.category), `${target.category}: ${target.title}`)}
        ${badge(target.v1, `v1 ${target.v1}`)}
        ${badge(target.intended === 'supported' ? 'supported' : 'not_supported', `intended ${target.intended}`)}
      </div>
    </div>` : '';
  const jump = ev.step != null ? `<button onclick="jumpToStepId(${Number(ev.step)})">跳到 evidence S${esc(ev.step)}</button>` : '';
  const snippet = c._evidence_snippet ? `
    <div class="tool-block">
      <div class="tool-head" onclick="toggle('snip-${esc(c.claim_id)}')"><b>matched evidence preview</b><span>open</span></div>
      <div class="tool-body" id="snip-${esc(c.claim_id)}">${esc(c._evidence_snippet)}</div>
    </div>` : '';
  return `<article class="claim-card ${target ? 'target' : ''}">
    <div class="claim-head">
      <div class="mini-actions">
        ${badge(c.verdict, verdictLabels[c.verdict] || c.verdict)}
        ${badge('type', c.claim_type || 'unknown')}
        ${target ? badge(catClass(target.category), target.category) : ''}
      </div>
      <div class="claim-id">${esc(c._claim_suffix)}</div>
    </div>
    <div class="claim-body">
      <div class="claim-span">${esc(c.claim_span)}</div>
      ${targetHtml}
      <div class="kv">
        <div class="k">Evidence pointer</div>
        <div class="v mini-actions">
          ${ev.channel ? badge('channel', ev.channel) : badge('needs_broader_context', 'no pointer')}
          ${ev.step != null ? badge('step', `S${ev.step}`) : ''}
          ${jump}
        </div>
      </div>
      ${ev.ref ? `<div class="ev-ref">${esc(ev.ref)}</div>` : ''}
      ${snippet}
      <div class="kv">
        <div class="k">Judge reason</div>
        <div class="v">${esc(c.reason || c.error || '')}</div>
      </div>
    </div>
  </article>`;
}

function toggle(id) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('open');
}

function jumpToStepId(stepId) {
  const t = filtered[currentTraj];
  const index = t.steps.findIndex(s => Number(s.step_id) === Number(stepId));
  if (index >= 0) selectStep(index);
}

function issuePositions() {
  const positions = [];
  filtered.forEach((t, ti) => {
    t.steps.forEach((s, si) => {
      if (s.claims.some(c => c._target || c.verdict === 'not_supported')) {
        positions.push({ti, si});
      }
    });
  });
  return positions;
}

function moveIssue(delta) {
  const positions = issuePositions();
  if (!positions.length) return;
  let idx = positions.findIndex(p => p.ti === currentTraj && p.si === currentStep);
  if (idx < 0) idx = 0;
  idx = (idx + delta + positions.length) % positions.length;
  currentTraj = positions[idx].ti;
  currentStep = positions[idx].si;
  renderList();
  renderCurrent();
}

function nextIssue() { moveIssue(1); }
function prevIssue() { moveIssue(-1); }

renderStats();
applyFilters();
if (filtered.length) {
  currentStep = firstInterestingStep(filtered[0]);
  renderCurrent();
}
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        default="binary_results_deepseek_chat_v2",
        help="Stage 2 result directory, relative to this script.",
    )
    parser.add_argument(
        "--exp-root",
        action="append",
        default=None,
        help="Trajectory root to scan. Can be passed multiple times.",
    )
    parser.add_argument(
        "--output-html",
        default="claim_action_review_ui.html",
        help="Output HTML path, relative to this script unless absolute.",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.is_absolute():
        results_dir = HERE / results_dir
    exp_roots = [Path(p) for p in args.exp_root] if args.exp_root else [
        RESEARCH / "experiments_v2" / "real",
        RESEARCH / "experiments_v2",
        RESEARCH / "experiments_v1",
    ]
    exp_roots = [p if p.is_absolute() else HERE / p for p in exp_roots]
    output_html = Path(args.output_html)
    if not output_html.is_absolute():
        output_html = HERE / output_html

    payload = _build_payload(results_dir, exp_roots)
    html = HTML.replace(
        "__DATA__",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    output_html.write_text(html, encoding="utf-8")

    meta = payload["meta"]
    print(f"Wrote {output_html}")
    print(
        "Claims: {total_claims}; trajectories: {total_trajectories}; "
        "not_supported: {ns}/{total_claims} ({rate:.1%})".format(
            ns=meta["verdict_counts"].get("not_supported", 0),
            rate=meta["not_supported_rate"],
            **meta,
        )
    )
    if meta["missing_trajectories"]:
        print(f"Missing trajectories: {len(meta['missing_trajectories'])}")


if __name__ == "__main__":
    main()
