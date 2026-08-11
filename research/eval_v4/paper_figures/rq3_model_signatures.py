#!/usr/bin/env python3
"""RQ3 main-text figure: the composition of halluci-action differs by model.

Portrait 100%-stacked columns, one per model -- the same encoding as the
original horizontal version, turned vertical so it can sit beside
tables/rq3_failure_modes.tex in a side-by-side float.

Why stacked composition rather than deviation-from-pooled
---------------------------------------------------------
The previous revision of this script drew each cell as (model share / pooled
share) on a log2 axis. That reads the difference directly, but 82% of all
instances are undisclosed reads, so under the pooled profile every model's
expected count in C3 is below 1, and four of the five C3 cells had to be drawn
hollow to warn that the ratio rests on nothing. Half the panel ended up saying
"do not trust this". Composition has the opposite failure mode -- it compresses
the rare classes -- but the claim this figure supports is about SHAPE
(deepseek-chat is mostly claim-side, gemini is almost entirely undisclosed
reads), and shape survives the compression. The rare-class detail lives in the
table beside it. The deviation version is kept in the scratchpad backup.

Counts are POST-exclusion
-------------------------
The original stacked bar plotted pre-exclusion counts (n=91, C1=47 for
deepseek-chat) and therefore contradicted the 715/66 in the prose on the same
page. The 21 exclusions are, per research/rq3_taxonomy/thematic: 1 gate-X,
1 extraction-artifact, 4 already-satisfied-restatement, 15 visibly-revised.
They are NOT uniform across models -- they take deepseek-chat from 92 to 78 and
qwen's C1 from 12 to 8, and never touch gemini or gpt-4o-mini -- so the
pre/post distinction changes the ranking, not just the totals. Every number
below is asserted against the totals the paper prints.

Regenerate:  python rq3_model_signatures.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT_DIR = Path(__file__).resolve().parent
LATEX_FIG_DIR = Path("/Users/maokaifang/Downloads/iclr/iclr2026/figures")
STEM = "rq3_failure_composition_by_model"

# Narrow enough to sit beside the 3-column failure-mode table inside 5.5in of
# textwidth: 2.65 (figure) + 2.55 (table) + column gap.
FIG_W, FIG_H = 2.65, 3.35

# --------------------------------------------------------------------------- #
# Data -- post-exclusion, Odoo, n = 715
# --------------------------------------------------------------------------- #

# Ordered by claim-side share descending, so the left-to-right reading of the
# figure is the ordering the second RQ3 paragraph walks through.
MODELS = [
    #  label                C1  C2  C3  C4w  C4r
    ("deepseek-chat",       34, 21,  0,   0,  23),
    ("deepseek-reasoner",   23,  4,  1,   8,  52),
    ("qwen3-8B",             8,  5,  3,  12, 153),
    ("gpt-4o-mini",          0,  3,  4,   2, 127),
    ("gemini-3.1-flash",     1,  0,  0,   0, 231),
]

# Bottom-to-top = the say-do chain, so a column's silhouette is "how far along
# the chain this model breaks". C4 is split because a hidden write and an
# undisclosed read carry different consequences.
CLASSES = [
    ("C1 unexecuted",        "#1F5C99"),  # claim-side: paper's blue, dark step
    ("C2 misgrounded",       "#4A87BF"),
    ("C3 unverified",        "#8FB8DC"),
    ("C4 hidden write",      "#B3590A"),  # severity: paper's orange
    ("C4 undisclosed read",  "#DFDFDF"),  # the benign bulk
]

TEXT, MUTED, RULE = "#333333", "#777777", "#B0B0B0"

counts = np.array([m[1:] for m in MODELS], dtype=float)   # 5 models x 5 classes
labels = [m[0] for m in MODELS]
totals = counts.sum(axis=1)

# --- assertions: nothing is published that the paper's totals do not support --
assert counts.sum() == 715, counts.sum()
assert list(counts.sum(axis=0)) == [66, 33, 8, 22, 586], counts.sum(axis=0)
assert list(totals) == [78, 88, 181, 136, 232], totals
claim_side = counts[:, :3].sum(axis=1) / totals
assert [round(x * 100, 1) for x in claim_side] == [70.5, 31.8, 8.8, 5.1, 0.4]
# the ordering claim in the docstring must hold for the data, not just the list
assert list(claim_side) == sorted(claim_side, reverse=True)

shares = counts / totals[:, None]

# --------------------------------------------------------------------------- #
# Draw
# --------------------------------------------------------------------------- #

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Nimbus Roman", "DejaVu Serif"],
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
fig.subplots_adjust(left=0.155, right=0.99, top=0.845, bottom=0.30)

x = np.arange(len(MODELS))
bottom = np.zeros(len(MODELS))

for j, (cname, color) in enumerate(CLASSES):
    h = shares[:, j]
    ax.bar(x, h, bottom=bottom, width=0.74, color=color,
           edgecolor="white", linewidth=0.6, zorder=3)
    # Label a segment only where the number actually fits inside it.
    for i in range(len(MODELS)):
        if h[i] >= 0.085:
            # white on the three dark fills, dark on the two light ones
            fg = "white" if j in (0, 1, 3) else TEXT
            ax.text(x[i], bottom[i] + h[i] / 2, f"{int(counts[i, j])}",
                    ha="center", va="center", fontsize=6.2, color=fg, zorder=4)
    bottom += h

# Claim-side share printed above each column: the one derived quantity the
# stack cannot be read off precisely, and the axis the paragraph argues along.
for i in range(len(MODELS)):
    ax.text(x[i], 1.028, f"{claim_side[i] * 100:.1f}%", ha="center", va="bottom",
            fontsize=6.4, color="#1F5C99")
    ax.text(x[i], -0.035, f"n={int(totals[i])}", ha="center", va="top",
            fontsize=6.0, color=MUTED)

ax.set_xlim(-0.65, len(MODELS) - 0.35)
ax.set_ylim(0, 1)
ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=38, ha="right", fontsize=6.6, color=TEXT)
ax.tick_params(axis="x", length=0, pad=9)
ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
ax.set_yticklabels(["0", "25", "50", "75", "100%"], fontsize=6.4, color=MUTED)
ax.tick_params(axis="y", length=0, pad=2)
ax.set_ylabel("share of the model's instances", fontsize=6.8, color=TEXT, labelpad=3)

for side in ("top", "right", "bottom", "left"):
    ax.spines[side].set_visible(False)
ax.axhline(0, color=RULE, lw=0.6, zorder=2)

# Legend above the plot, two columns, chain order preserved.
handles = [plt.Rectangle((0, 0), 1, 1, facecolor=c, edgecolor="white", lw=0.5)
           for _, c in CLASSES]
leg = fig.legend(handles, [n for n, _ in CLASSES],
                 loc="upper left", bbox_to_anchor=(0.005, 1.005),
                 ncol=2, frameon=False, fontsize=6.2,
                 handlelength=1.0, handleheight=0.75,
                 columnspacing=0.8, labelspacing=0.28, handletextpad=0.4)
for t in leg.get_texts():
    t.set_color(TEXT)

for ext in ("pdf", "png"):
    p = OUT_DIR / f"{STEM}.{ext}"
    fig.savefig(p, dpi=400, facecolor="white")
    if LATEX_FIG_DIR.is_dir():
        shutil.copy2(p, LATEX_FIG_DIR / p.name)
    print("wrote", p)

print(f"\ncanvas {FIG_W} x {FIG_H} in")
for i, lab in enumerate(labels):
    print(f"  {lab:<20} n={int(totals[i]):<4} "
          f"C1={int(counts[i,0]):<3} C2={int(counts[i,1]):<3} C3={int(counts[i,2]):<2} "
          f"C4w={int(counts[i,3]):<3} C4r={int(counts[i,4]):<4} "
          f"claim-side={claim_side[i]*100:.1f}%")
