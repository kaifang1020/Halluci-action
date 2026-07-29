"""Build a ground-truth OUTCOME spec for an AppWorld task, for the requirement judge.

Most AppWorld tasks have no authored step sequence (only 147/732 ship a
`ground_truth/solution.py`), but ALL 732 ship a `test_data.json` — the list of
natural-language grading requirements — plus `public_data.json` / `private_data.json`
that bind the placeholders those requirements reference. Together they are a precise,
state-based goal spec ("1 PaymentRequest added, recipient_id = 36, amount = 299"),
which is exactly what the requirement rubric needs (required = correct object +
correct effect; forbidden = wrong object/effect). We resolve the placeholders and
hand the result to the judge as `ground_truth_steps`.

This is a task ORACLE for judging requirement status, not evidence the agent knew a
fact — matching how the Odoo path uses authored ground truth.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_TASKS_ROOT = Path("/Users/maokaifang/appworld-root/data/tasks")


def _resolve_placeholders(text: str, public: dict, private: dict) -> str:
    """Replace `public_data.X` / `private_data.X` tokens with their concrete values."""
    def sub(m: re.Match) -> str:
        source, key = m.group(1), m.group(2)
        val = (public if source == "public_data" else private).get(key)
        return str(val) if val is not None else m.group(0)
    return re.sub(r"\b(public_data|private_data)\.([A-Za-z_][A-Za-z0-9_]*)", sub, text)


def load_ground_truth_outcomes(
    task_id: str, tasks_root: Path = DEFAULT_TASKS_ROOT
) -> list[dict[str, str]]:
    """Return [{"id": "GT-1", "text": "<resolved requirement>"}, ...] for a task.

    Skips the trivial `assert answers match` row (no actionable outcome for an
    action task whose answer is null).
    """
    gt = tasks_root / task_id / "ground_truth"
    test_data = json.loads((gt / "test_data.json").read_text(encoding="utf-8"))
    public = json.loads((gt / "public_data.json").read_text(encoding="utf-8"))
    private = json.loads((gt / "private_data.json").read_text(encoding="utf-8"))

    out: list[dict[str, str]] = []
    for i, row in enumerate(test_data, start=1):
        req = (row.get("requirement") or "").strip()
        if not req or req.lower().startswith("assert answers match"):
            continue
        text = _resolve_placeholders(req.replace("\n", " "), public, private)
        out.append({"id": f"GT-{i}", "text": text})
    return out


if __name__ == "__main__":
    import sys
    tid = sys.argv[1] if len(sys.argv) > 1 else "2e9b91e_1"
    for r in load_ground_truth_outcomes(tid):
        print(f"  {r['id']}: {r['text']}")
