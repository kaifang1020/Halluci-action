"""Parse the AppWorld codebook.md into the `system_constraints` shape the judges
consume (a list of {"id", "text"} dicts, injected as SYSTEM_CONSTRAINTS_JSON).

Same rule line format as Halluci-Action's Odoo codebook:  **<ID>** · <text>
(optionally with a *(tasks: ...)* / *(apps: ...)* scope tag before the `·`).
"""
from __future__ import annotations

import re
from pathlib import Path

DEFAULT_CODEBOOK = Path(__file__).resolve().parent / "codebook.md"

_RULE_RE = re.compile(
    r"^\*\*([A-Z]+-\d{2})\*\*"          # bold rule id, e.g. **V-01**
    r"(?:\s*\*\([^)]*\)\*)*"            # optional *(apps: ...)* / *(tasks: ...)* tags
    r"\s*·\s*(.+?)\s*$"                 # ·  then the rule text
)


def load_codebook_constraints(path: Path = DEFAULT_CODEBOOK) -> list[dict[str, str]]:
    """Return [{"id": "G-01", "text": "..."}, ...] for every rule in the codebook."""
    out: list[dict[str, str]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = _RULE_RE.match(line.strip())
        if m:
            out.append({"id": m.group(1), "text": m.group(2)})
    return out


if __name__ == "__main__":  # quick self-check
    rules = load_codebook_constraints()
    print(f"{len(rules)} rules")
    for r in rules:
        print(f"  {r['id']}: {r['text'][:70]}")
