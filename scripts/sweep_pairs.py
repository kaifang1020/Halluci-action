#!/usr/bin/env python3
"""Read a sweep YAML and emit one TSV line per (provider, model, kl).

Bash uses ``mapfile -t < <(python sweep_pairs.py path.yaml)`` to consume.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: sweep_pairs.py <sweep.yaml>", file=sys.stderr)
        return 2
    cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
    default_kl = (cfg.get("defaults") or {}).get("kl", "KL1")
    for entry in cfg.get("agents") or []:
        provider = entry["provider"]
        model = entry["model"]
        kl = entry.get("kl", default_kl)
        print(f"{provider}\t{model}\t{kl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
