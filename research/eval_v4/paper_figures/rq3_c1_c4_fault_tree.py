#!/usr/bin/env python3
"""Figure: the C1-C4 fault tree -- where the say-do alignment chain breaks.

This figure predates the other paper_figures scripts and had no generator; it was
rebuilt here from the published PDF so it can be regenerated and edited like the
rest. Layout, colours and proportions are taken from the original (its box
geometry was measured off the 400 dpi PNG), so it reads as the same figure.

What changed in the rebuild
---------------------------
1. C1's question. It read "Was the operation executed?"; it now reads
   "Was any operation attempted?".

   The paper's matching relation requires an executed action to agree with the
   claim on operation type AND key parameters. An action that does the right kind
   of thing to the wrong target therefore does not match either -- it lands in the
   same empty-match bucket as an action that never happened. Those two cases are
   C2 and C1 respectively, so C1 cannot be "was it executed": that phrasing also
   covers the C2 cases and makes the two gates overlap. C1 has to be the weaker
   question -- was anything attempted at all -- with C2 catching "something was
   attempted but it did not match the claimed target".

   Nothing else in the figure implies the old reading, so nothing else moved:
     * "C1 Execution" is the gate NAME, and the paper's own prose uses it that way
       ("86 fail at execution (C1)"), so it stays. It names the stage of the chain,
       not the test.
     * "Unexecuted commitment" remains exactly right for the failure: a commitment
       for which no operation was ever attempted. Sec. 7 describes these as claims
       "for which no matching operation appears in the trace", which is the new
       wording, not the old one.
     * C2 "Correct target and parameters?" already carries the attempted-but-wrong
       reading and is unchanged, as are C3 (claimed result) and C4 (disclosure).

2. No title inside the figure. The original carried "Where does the say-do
   alignment chain break?" as in-figure type; house style puts that in the LaTeX
   caption, and \\ref{fig:rq3-fault-tree} already has one. Dropping it also takes
   the canvas from 2.39 in to 2.00 in of height, which the submission needs.

3. House style otherwise: serif stack, Type-42 embedding, exact canvas, one text
   column wide.

Counts: C1 66, C2 33, C3 8, C4 608, over 715 coded instances with
the exclusions listed in Sec. 6.3. They are asserted below rather than trusted.

Colour carries no information here -- every box is directly labelled with its gate
id and name, and the counts are printed -- so the four hues are decoration that
groups a gate with its outcome, and the figure survives grayscale and any CVD type
without them.

Regenerate:  python rq3_c1_c4_fault_tree.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

OUT_DIR = Path(__file__).resolve().parent
LATEX_FIG_DIR = Path("/Users/maokaifang/Downloads/iclr/iclr2026/figures")
STEM = "rq3_c1_c4_fault_tree"

# One text column wide. The original was 5.66 x 2.39 in with an in-figure title;
# dropping the title and trimming to the standard column gives 5.5 x 2.00.
FIG_W, FIG_H = 5.5, 2.00

# --------------------------------------------------------------------------- #
# Style
# --------------------------------------------------------------------------- #

SURFACE = "#FFFFFF"
TEXT = "#333333"
MUTED = "#777777"
GATE_FILL = "#F8F9FA"
DIVIDER = "#E8EAED"
LINK = "#8A8A8A"          # the grey C1->C2->C3 chain arrows

BORDER_LW = 1.15
ROUND = 0.055             # corner radius, inches


def _tint(hex_color: str, alpha: float = 0.30) -> tuple:
    """The outcome-box fill: `alpha` of the border colour over white.

    Measured off the original figure -- e.g. C3's #7E72A8 border against its
    #D9D2E9 fill is exactly a 30% blend -- so the rebuild reproduces the tints
    rather than approximating them by eye.
    """
    r, g, b = to_rgb(hex_color)
    return tuple(alpha * c + (1 - alpha) * 1.0 for c in (r, g, b))


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #

# (gate id, gate name, question, outcome name, n, colour, x0, x1)
# x extents are the original figure's, rescaled to the 5.5 in column.
GATES = [
    ("C1", "Execution", "Was any operation attempted?",
     "Unexecuted commitment", 66, "#54789C", 0.044, 1.278),
    ("C2", "Grounding", "Correct target and parameters?",
     "Misgrounded execution", 33, "#C69642", 1.373, 2.607),
    ("C3", "Verification", "Was the claimed result achieved?",
     "Unverified outcome", 8, "#7E72A8", 2.702, 3.936),
    ("C4", "Disclosure", "Was every action disclosed?",
     "Undisclosed execution", 608, "#BA6654", 4.164, 5.454),
]

TOTAL = 715               # coded instances; see the exclusions note in Sec. 6.3
assert sum(g[4] for g in GATES) == TOTAL, "gate counts must exhaust the taxonomy"

DIVIDER_X = 4.024         # between the claim-anchored block and C4

# Vertical bands, inches from the bottom of the canvas.
GATE_Y0, GATE_Y1 = 1.2475, 1.8225
OUT_Y0, OUT_Y1 = 0.300, 0.830
LINK_Y = 1.590            # height of the horizontal chain arrows
GROUP_Y = 1.912
FOOT_Y = 0.075


# --------------------------------------------------------------------------- #
# Plot
# --------------------------------------------------------------------------- #


def _box(ax, x0, x1, y0, y1, facecolor, edgecolor):
    ax.add_patch(
        FancyBboxPatch(
            (x0, y0), x1 - x0, y1 - y0,
            boxstyle=f"round,pad=0,rounding_size={ROUND}",
            facecolor=facecolor, edgecolor=edgecolor,
            linewidth=BORDER_LW, zorder=2,
        )
    )


def build():
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "font.size": 7,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "figure.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
        }
    )

    fig = plt.figure(figsize=(FIG_W, FIG_H))
    # One axes over the whole canvas with data units == inches, so corner radii
    # are circular and every measured coordinate can be written as-is.
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, FIG_W)
    ax.set_ylim(0, FIG_H)
    ax.set_axis_off()

    # Divider: the claim-anchored block (C1-C3) against the action-anchored one.
    ax.plot([DIVIDER_X, DIVIDER_X], [0.13, 1.935],
            color=DIVIDER, linewidth=1.1, zorder=1, solid_capstyle="butt")

    claim_mid = (GATES[0][6] + GATES[2][7]) / 2
    action_mid = (GATES[3][6] + GATES[3][7]) / 2
    ax.text(claim_mid, GROUP_Y, "claim-anchored", ha="center", va="center",
            fontsize=6.0, color=MUTED, zorder=3)
    ax.text(action_mid, GROUP_Y, "action-anchored", ha="center", va="center",
            fontsize=6.0, color=MUTED, zorder=3)

    for gate, name, question, outcome, n, color, x0, x1 in GATES:
        cx = (x0 + x1) / 2

        # Gate box: near-white fill, coloured rule.
        _box(ax, x0, x1, GATE_Y0, GATE_Y1, GATE_FILL, color)
        ax.text(cx, GATE_Y1 - 0.185, f"{gate}   {name}", ha="center", va="center",
                fontsize=7.8, color=TEXT, fontweight="bold", zorder=3)
        ax.text(cx, GATE_Y1 - 0.395, question, ha="center", va="center",
                fontsize=6.0, color=TEXT, zorder=3)

        # Outcome box: the gate's colour at 30% over white.
        _box(ax, x0, x1, OUT_Y0, OUT_Y1, _tint(color), color)
        ax.text(cx, OUT_Y1 - 0.185, outcome, ha="center", va="center",
                fontsize=7.2, color=TEXT, fontweight="bold", zorder=3)
        ax.text(cx, OUT_Y1 - 0.375, f"$n$ = {n}", ha="center", va="center",
                fontsize=7.0, color=TEXT, zorder=3)

        # The "no" branch from gate to outcome.
        ax.add_patch(
            FancyArrowPatch(
                (cx, GATE_Y0 - 0.012), (cx, OUT_Y1 + 0.028),
                arrowstyle="-|>", mutation_scale=6.5,
                color=color, linewidth=0.9, shrinkA=0, shrinkB=0, zorder=3,
            )
        )
        ax.text(cx + 0.055, (GATE_Y0 + OUT_Y1) / 2 + 0.035, "no",
                ha="left", va="center", fontsize=5.8, color=color, zorder=3)

    # The claim-side chain: a failed gate passes the claim to the next one.
    for (_, _, _, _, _, _, _, x_end), (_, _, _, _, _, _, x_start, _) in zip(
            GATES[:2], GATES[1:3]):
        ax.add_patch(
            FancyArrowPatch(
                (x_end + 0.014, LINK_Y), (x_start - 0.014, LINK_Y),
                arrowstyle="-|>", mutation_scale=6.5,
                color=LINK, linewidth=0.9, shrinkA=0, shrinkB=0, zorder=3,
            )
        )

    ax.text(
        FIG_W / 2, FOOT_Y,
        f"Every one of the {TOTAL} coded instances maps to exactly one gate.",
        ha="center", va="center", fontsize=5.6, color=MUTED, zorder=3,
    )
    return fig


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> None:
    print(f"-- C1-C4 fault tree, {TOTAL} genuine instances "
          f"(after the exclusions listed in the text) --")
    for gate, name, question, outcome, n, color, _, _ in GATES:
        print(f"  {gate}  {name:13s} {question:34s} -> {outcome:22s} "
              f"n={n:4d} ({100 * n / TOTAL:5.1f}%)  {color}")
    print(f"  {'':6s}{'':13s} {'':34s}    {'total':22s} "
          f"n={sum(g[4] for g in GATES):4d}")
    print("\n  C1's question now reads 'Was any operation attempted?' "
          "(was: 'Was the operation executed?').")
    print("  Gate names, outcome names and C2-C4 questions are unchanged; "
          "none of them implied the old reading.")

    fig = build()
    targets = [OUT_DIR / f"{STEM}.png", OUT_DIR / f"{STEM}.pdf",
               *([LATEX_FIG_DIR / f"{STEM}.png", LATEX_FIG_DIR / f"{STEM}.pdf"]
                 if LATEX_FIG_DIR.is_dir() else [])]

    print()
    for path in targets:
        # No bbox_inches="tight": the canvas must stay exactly FIG_W x FIG_H.
        kwargs = {"dpi": 400} if path.suffix == ".png" else {}
        fig.savefig(path, **kwargs)
        print(f"wrote {path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
