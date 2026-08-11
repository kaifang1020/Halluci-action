#!/usr/bin/env python3
"""Shared plumbing for replaying recorded trajectories into a fresh AppWorld env.

PURELY ADDITIVE.  Nothing here mutates any existing artifact; it only reads
``runs/judge_summary.jsonl``, ``runs/trajectories/**`` and ``runs/audits/**`` and
drives ``appworld`` in-process.  No LLM is called at any point.

WHY REPLAY WORKS AT ALL (the soundness argument, verified empirically)
---------------------------------------------------------------------
``AppWorld.evaluate()`` delegates to ``appworld.evaluator.evaluate_task``, which
loads the "end" model collection from
``<experiment_outputs>/<experiment_name>/tasks/<task_id>/dbs``.  The loader goes
through ``CachedDBHandler``, which -- per the comment in ``evaluator.py`` -- finds
the LIVE IN-MEMORY DB when the environment is still open, and only falls back to
disk otherwise.  Our replay never calls ``world.execute`` (which is the only thing
that flushes state to disk), so the in-memory path is the one that matters: the
evaluator sees exactly the writes our direct ``world.apis.<app>.<api>()`` calls
made, provided ``evaluate()`` is called BEFORE ``close()``.

That is not an assumption -- ``phase1_validate.py`` runs a null-replay control
(construct the world, replay nothing, evaluate) next to the real replay.  On
``024c982_1``/ds_chat the control scores 0/7 and the replay 5/7, so the evaluator
demonstrably reads our writes.

EXPERIMENT NAME
---------------
``experiment_name`` MUST embed the model tag.  The original runs all shared
``halluci_action_appworld`` (``runner.py:104``), so five models wrote into one
``tasks/<task_id>/dbs`` directory and overwrote each other -- which is precisely
why the success flag cannot be recovered from disk today.  Every entry point here
uses ``f"{prefix}_{tag}"``.

TWO EVALUATOR ARTIFACTS OF REPLAY (both diagnosed, one fixed, one reported)
--------------------------------------------------------------------------
1. STALE MODEL HASHES -- FIXED HERE.  ``models.changed_model_names()`` first
   filters candidates by comparing the ``ModelHash`` table of the start DB against
   the end DB, and that table is only refreshed by ``AppWorld._save_state``, which
   AppWorld calls at the end of every ``world.execute``.  A replay that drives the
   APIs directly never triggers it, so the end hashes still hold their
   initialize-time values, every model looks unchanged, and the
   ``assert model changes match <models>`` test fails even when the write plainly
   landed (``changed_records`` -- a real row diff -- saw it).  We therefore call
   ``world._save_state(world.output_db_home_path_on_disk)`` once before
   ``evaluate()``.  That is pure bookkeeping: it recomputes hashes over the state
   the replay already produced and mutates no application data.  Verified on
   ``024c982_1``/ds_chat (5/7 -> 6/7) and ``d6ac34d_1``/ds_reasoner (7/9 -> 8/9).

2. THE ANSWER TEST -- REPORTED, NOT FIXED.  Every task carries an
   ``assert answers match`` test comparing ``ground_truth_answer`` to the answer
   passed to ``supervisor.complete_task``.  The halluci-action harness ends an
   episode with a natural-language report instead, so only 3 of 2,405 recorded
   trajectories ever call ``supervisor__complete_task`` and the predicted answer is
   ``<<not_given>>`` almost everywhere.  Strict AppWorld success is consequently
   ~0 for structural reasons that have nothing to do with the agent's competence.
   We record BOTH flags: ``success_strict`` (AppWorld's raw verdict) and
   ``success_state`` (every non-answer test passes).  84.6% of the tasks in this
   corpus have a null ground-truth answer, so for those two the difference is
   exactly "did the agent call complete_task"; for the other 15.4% dropping the
   test is a genuine relaxation and is counted separately.

CONCURRENCY
-----------
``AppWorld.initialize()`` calls ``AppWorld.close_all()``, so a single process can
hold exactly ONE open world.  In-process parallelism is therefore impossible.
Cross-process parallelism is safe only if the workers never share an
``(experiment_name, task_id)`` pair; we shard by tag, which guarantees it.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

BASE = Path(__file__).resolve().parent
RUNS = BASE / "runs"
TRAJ_DIR = RUNS / "trajectories"
AUDIT_DIR = RUNS / "audits"
JUDGE_SUMMARY = RUNS / "judge_summary.jsonl"

TAGS = ["ds_chat", "ds_reasoner", "gemflash", "gpt4omini", "qwen8b"]
TAG_TO_MODEL = {
    "ds_chat": "deepseek-chat",
    "ds_reasoner": "deepseek-reasoner",
    "gemflash": "gemini-3.1-flash",
    "gpt4omini": "gpt-4o-mini",
    "qwen8b": "qwen3-8B",
}


# --------------------------------------------------------------------- timing

def wall() -> float:
    """Real elapsed seconds, immune to AppWorld's freezegun clock.

    ``AppWorld`` freezes ``time.time`` / ``datetime.now`` to the task datetime for
    the lifetime of the world, so ``time.time()`` deltas across a world are
    meaningless (they came back negative in the smoke test).  ``os.times()[4]``
    is the OS-level elapsed real time and is not patched.
    """
    return os.times()[4]


# ------------------------------------------------------------------ cell load

TAG_TO_TRAJ_SUFFIX = {
    "ds_chat": "deepseek_deepseek_chat",
    "ds_reasoner": "deepseek_deepseek_reasoner",
    "gemflash": "gemini_vertexai_hs3645_gemini_3_flash_preview",
    "gpt4omini": "openai_gpt_4o_mini",
    "qwen8b": "qwen_qwen3_8b",
}


def load_cells(include_har_only: bool = True) -> list[dict[str, Any]]:
    """One row per judged (task, tag) cell, deduped keeping the LAST occurrence.

    The judge's own ``traj`` field names the trajectory file that was actually
    judged (retries carry an ``_rNN`` suffix), so the success flag joins to the
    HAR row for the same run.  We never guess the filename for those cells.

    ``include_har_only`` additionally picks up cells that appear in
    ``har_trajectories_appworld.csv`` but have no ``judge_summary`` line (57 as of
    this writing -- the summary write evidently failed for them, though the judge
    artifacts they were built from exist).  Without them the phase-3 join silently
    drops HAR rows.  They are only admitted when EXACTLY ONE trajectory file
    matches ``<TASK>_<suffix>[_rNN].json``, so no filename is ever guessed between
    a base run and a retry; all 57 are unambiguous today.  Provenance is recorded
    in the ``source`` field.
    """
    rows = [json.loads(line) for line in JUDGE_SUMMARY.read_text().splitlines() if line.strip()]
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        cells[(row["task"], row["tag"])] = row

    index = trajectory_index()
    out = []
    for (task, tag), row in cells.items():
        traj = row["traj"]
        out.append(
            {
                "task": task,
                "tag": tag,
                "model": row.get("model"),
                "traj": traj,
                "traj_path": index.get(traj),
                "audit_path": AUDIT_DIR / traj.replace(".json", "__audit.json"),
                "source": "judge_summary",
            }
        )

    if include_har_only:
        out.extend(_har_only_cells(set(cells), index))

    out.sort(key=lambda c: (c["task"], c["tag"]))
    return out


def _har_only_cells(known: set[tuple[str, str]], index: dict[str, Path]) -> list[dict[str, Any]]:
    import csv
    import re

    csv_path = BASE / "har_trajectories_appworld.csv"
    if not csv_path.exists():
        return []
    out = []
    seen: set[tuple[str, str]] = set()
    with csv_path.open() as handle:
        for row in csv.DictReader(handle):
            key = (row["task_id"], row["tag"])
            if key in known or key in seen or row["tag"] not in TAG_TO_TRAJ_SUFFIX:
                continue
            stem = f"{row['task_id'].upper().replace('_', '-')}_{TAG_TO_TRAJ_SUFFIX[row['tag']]}"
            pattern = re.compile(re.escape(stem) + r"(_r\d+)?\.json$")
            candidates = [name for name in index if pattern.fullmatch(name)]
            if len(candidates) != 1:
                continue  # ambiguous base-vs-retry: refuse to guess
            seen.add(key)
            out.append(
                {
                    "task": row["task_id"],
                    "tag": row["tag"],
                    "model": row.get("model"),
                    "traj": candidates[0],
                    "traj_path": index[candidates[0]],
                    "audit_path": AUDIT_DIR / candidates[0].replace(".json", "__audit.json"),
                    "source": "har_csv",
                }
            )
    return out


def trajectory_index() -> dict[str, Path]:
    """basename -> path, over ``runs/trajectories/**`` excluding any ``_archive``."""
    index: dict[str, Path] = {}
    dupes: dict[str, list[Path]] = defaultdict(list)
    for path in TRAJ_DIR.rglob("*.json"):
        if "_archive" in str(path):
            continue
        dupes[path.name].append(path)
        index[path.name] = path
    for name, paths in dupes.items():
        if len(paths) > 1:  # pragma: no cover - none today; loud if that changes
            raise RuntimeError(f"ambiguous trajectory basename {name}: {paths}")
    return index


def extract_calls(trajectory: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every tool call, in execution order, as ``(tool_name, parameters)``."""
    return [
        (call["tool_name"], call.get("parameters") or {})
        for step in trajectory.get("steps") or []
        for call in (step.get("tool_calls") or [])
    ]


def load_audit_records(path: Path) -> list[dict[str, Any]]:
    """The recorded per-action audit records (each carries a ``state_delta``)."""
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("records") or []


# ------------------------------------------------------------------- replay

def answer_test_split(tracker: Any) -> dict[str, Any]:
    """Split AppWorld's tests into answer tests and final-state tests.

    A test is answer-related iff its requirement text mentions "answer".  Scanning
    all 493 ``ground_truth/evaluation.py`` files in this corpus turns up exactly
    five such phrasings ("assert answers match." in 488 tasks, plus four bespoke
    variants), every one of which compares ``predicted_answer`` to the ground
    truth -- so the keyword is a clean partition, not a heuristic.

    ``success_state`` is True when every NON-answer test passes.  For a task whose
    ground-truth answer is null this is exactly the verdict AppWorld would return
    had the agent called ``supervisor.complete_task()``.
    """
    report = tracker.to_dict()
    passes = report.get("passes") or []
    failures = report.get("failures") or []

    def is_answer(entry: dict[str, Any]) -> bool:
        return "answer" in (entry.get("requirement") or "").lower()

    state_failures = [f for f in failures if not is_answer(f)]
    answer_failures = [f for f in failures if is_answer(f)]
    return {
        "success_state": len(state_failures) == 0,
        "state_pass_count": len([p for p in passes if not is_answer(p)]),
        "state_num_tests": len([t for t in passes + failures if not is_answer(t)]),
        "answer_test_failed": len(answer_failures) > 0,
        "n_answer_tests": len([t for t in passes + failures if is_answer(t)]),
        "failed_requirements": [
            " ".join((f.get("requirement") or "").split())[:200] for f in failures
        ][:12],
    }


def replay_cell(
    cell: dict[str, Any],
    experiment_prefix: str = "tsr",
    gateway: bool = False,
) -> dict[str, Any]:
    """Replay one cell into a fresh world and run AppWorld's own evaluator.

    ``gateway=True`` routes every call through ``AppWorldGateway`` so the replay
    produces the same ``state_delta`` shape the original run recorded -- that is
    what the determinism check compares against.  It costs two full app-DB
    snapshots per call, so the bulk run leaves it off.
    """
    from appworld import AppWorld

    from research.appworld_backend.tools import AppWorldToolExecutor

    trajectory = json.loads(Path(cell["traj_path"]).read_text())
    calls = extract_calls(trajectory)
    task_id = trajectory["task_id"]

    started = wall()
    world = AppWorld(task_id=task_id, experiment_name=f"{experiment_prefix}_{cell['tag']}")
    errors = 0
    observed: list[dict[str, Any]] = []
    try:
        executor = AppWorldToolExecutor(world=world, exposed_apis=[name for name, _ in calls])
        driver: Any = executor
        if gateway:
            from research.appworld_backend.gateway import AppWorldGateway

            driver = AppWorldGateway(world, executor)

        for index, (name, params) in enumerate(calls):
            record: dict[str, Any] = {"i": index, "tool_name": name}
            if gateway:
                # The gateway records errors instead of raising (same contract as
                # the original run), so read the status off the return value.
                result = driver.execute(name, params, step_id=index)
                record["status"] = result.get("status")
                record["state_delta"] = result.get("state_delta") or {}
                if result.get("status") != "success":
                    errors += 1
                    record["error"] = str(result.get("message"))[:300]
            else:
                try:
                    driver.execute(name, params)
                    record["status"] = "success"
                except Exception as exc:  # noqa: BLE001
                    # Count it and carry on: a call that failed on replay is
                    # faithful to a call that failed in the original run.
                    errors += 1
                    record["status"] = "error"
                    record["error"] = f"{type(exc).__name__}: {exc}"[:300]
            observed.append(record)

        # Refresh AppWorld's own ModelHash bookkeeping before evaluating -- see the
        # module docstring, artifact 1.  Never skip this: without it every
        # `changed_model_names` assertion fails spuriously.
        world._save_state(world.output_db_home_path_on_disk)

        tracker = world.evaluate(suppress_errors=True)
        outcome = {
            "success_strict": bool(tracker.success),
            "pass_count": int(tracker.pass_count),
            "fail_count": int(tracker.fail_count),
            "num_tests": int(tracker.num_tests),
            "pass_percentage": float(tracker.pass_percentage),
            **answer_test_split(tracker),
        }
    finally:
        try:
            world.close()
        except Exception:  # noqa: BLE001 - close is best-effort
            pass

    return {
        "task": cell["task"],
        "tag": cell["tag"],
        "traj": cell["traj"],
        **outcome,
        "n_calls": len(calls),
        "replay_errors": errors,
        "secs": round(wall() - started, 2),
        "observed": observed,
    }


# ----------------------------------------------------------- delta comparison

def normalise_delta(delta: dict[str, Any]) -> dict[str, Any]:
    """Canonical form of a ``state_delta`` for equality testing.

    Sorts each table's change list by ``(op, str(id))`` so ordering differences
    that ``compute_state_delta`` already treats as cosmetic do not register as a
    mismatch.  Nothing is dropped: row contents, ids and timestamps are all kept,
    so this is a STRICT comparison of the recorded database effect.
    """
    out: dict[str, Any] = {}
    for table, changes in (delta or {}).items():
        if not isinstance(changes, list):
            continue
        out[table] = sorted(
            (json.loads(json.dumps(change, default=str, sort_keys=True)) for change in changes),
            key=lambda change: (str(change.get("op")), str(change.get("id"))),
        )
    return out


def delta_signature(delta: dict[str, Any]) -> set[tuple[str, str, str]]:
    """``{(table, op, id)}`` -- which rows changed and how, ignoring contents."""
    return {
        (table, str(change.get("op")), str(change.get("id")))
        for table, changes in (delta or {}).items()
        if isinstance(changes, list)
        for change in changes
    }


def compare_to_audit(observed: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-action comparison of the replay against the original run's audit.

    Actions are aligned positionally (the audit's ``records`` are written in call
    order by the same loop that emitted ``steps[].tool_calls``); the tool name is
    asserted at each index so a silent misalignment cannot pass.
    """
    n = min(len(observed), len(records))
    exact = structural = status_match = name_match = 0
    mismatches: list[dict[str, Any]] = []
    for i in range(n):
        obs, rec = observed[i], records[i]
        rec_result = rec.get("gateway_result") or {}
        same_name = obs.get("tool_name") == rec.get("tool_name")
        name_match += int(same_name)
        if obs.get("status") == rec_result.get("status"):
            status_match += 1
        obs_delta = normalise_delta(obs.get("state_delta") or {})
        rec_delta = normalise_delta(rec_result.get("state_delta") or {})
        is_exact = obs_delta == rec_delta
        is_structural = delta_signature(obs_delta) == delta_signature(rec_delta)
        exact += int(is_exact)
        structural += int(is_structural)
        if not is_exact and len(mismatches) < 5:
            mismatches.append(
                {
                    "i": i,
                    "tool_name": obs.get("tool_name"),
                    "structural": is_structural,
                    "obs_tables": sorted(obs_delta),
                    "rec_tables": sorted(rec_delta),
                    "obs_sig": sorted(map(str, delta_signature(obs_delta)))[:6],
                    "rec_sig": sorted(map(str, delta_signature(rec_delta)))[:6],
                }
            )
    return {
        "n_compared": n,
        "n_observed": len(observed),
        "n_recorded": len(records),
        "aligned": len(observed) == len(records) and name_match == n,
        "exact": exact,
        "structural": structural,
        "status_match": status_match,
        "cell_exact": n > 0 and exact == n and len(observed) == len(records),
        "cell_structural": n > 0 and structural == n and len(observed) == len(records),
        "mismatches": mismatches,
    }


# ------------------------------------------------------------------ jsonl io

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line from a crash; drop it
    return out


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def chunk(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


__all__ = [
    "BASE", "RUNS", "TAGS", "TAG_TO_MODEL",
    "answer_test_split", "append_jsonl", "chunk", "compare_to_audit", "extract_calls",
    "load_audit_records", "load_cells", "read_jsonl", "replay_cell",
    "trajectory_index", "wall",
]
