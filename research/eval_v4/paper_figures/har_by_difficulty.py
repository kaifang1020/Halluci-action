#!/usr/bin/env python3
"""Appendix figure + tables: HAR is a property of the model, not of task difficulty.

Odoo only. AppWorld tasks carry no difficulty label, so the difficulty axis
exists in exactly one environment and this figure/table set says so.

Figure
------
(a) One line per model across the four difficulty levels, in benchmark order
    (easy, medium, hard, comprehensive). The point of drawing them separately
    rather than pooled is that the pooled flatness could in principle be an
    averaging artifact -- five steep-but-opposing trends would average flat.
    They are not: the vertical separation between models dwarfs the left-right
    movement within any one of them.
(b) The same claim as two spans on the SAME y scale as (a): the span of the
    five per-model HARs against the span of the four per-difficulty HARs.
    Ticks on each span are the individual marginal values, so (b) also carries
    the pooled-per-difficulty numbers that (a) deliberately leaves out.

Aggregation (must match the paper text and the main results table)
------------------------------------------------------------------
Macro averaging over trajectories, verdict definition. A trajectory is excluded
from a metric when that metric is undefined (blank / NaN); exclusion is
PER-METRIC, not listwise, so a trajectory with a defined r_verdict but a blank
p_verdict still contributes to done-not-said. float('nan') is not None and
NaN != NaN, so the blank test is an explicit math.isnan guard.

    said-not-done = mean_traj(1 - p_verdict)
    done-not-said = mean_traj(1 - r_verdict)
    HAR           = mean_traj(har_verdict)

Range statements ("spread X pp") follow the convention already used in the
appendix table footnotes: the difference of the ROUNDED endpoints, so the
footnote is arithmetic the reader can do on the printed column. Both the
rounded and the unrounded span are printed to stdout.

Regenerate:  python har_by_difficulty.py
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[2]                     # research/eval_v4/paper_figures -> repo
DATA_DIR = REPO_ROOT / "research" / "appworld_backend"

CSV_PATH = DATA_DIR / "har_trajectories_odoo.csv"

# Extra copy destinations (the LaTeX tree). Skipped silently if absent.
LATEX_FIG_DIR = Path("/Users/maokaifang/Downloads/iclr/iclr2026/figures")
LATEX_TAB_DIR = Path("/Users/maokaifang/Downloads/iclr/iclr2026/tables")

# Appendix figure: one text column wide, and as short as the content allows --
# the submission is over its page limit, so height is the scarce resource.
FIG_W, FIG_H = 5.5, 2.05

DIFFICULTIES = ["easy", "medium", "hard", "comprehensive"]

# Display order = ascending pooled HAR, which happens to be the bottom-to-top
# order of the lines in panel (a), so the reader's eye and the label column agree.
MODELS = [
    ("deepseek-chat", "deepseek-chat"),
    ("deepseek-reasoner", "deepseek-reasoner"),
    ("gemini-3.1-flash", "gemini-3.1-flash"),
    ("gpt-4o-mini", "gpt-4o-mini"),
    ("qwen3-8B", "qwen3-8B"),
]

# A model x difficulty cell with fewer than this many HAR-defined trajectories is
# drawn hollow. The comprehensive column is thin for every model (2-11 defined
# trajectories), and qwen3-8B's comprehensive cell in particular rests on 2 --
# an unmarked filled marker there would read as a steep, well-supported rise.
THIN_N = 10

# --------------------------------------------------------------------------- #
# Style
# --------------------------------------------------------------------------- #

SURFACE = "#FFFFFF"
TEXT = "#333333"
MUTED = "#777777"
GRID = "#E6E6E6"
RULE = "#B0B0B0"

# Categorical slots 1-5 of the documented dataviz palette, in fixed slot order.
# The dark-mode steps of those same five hues are used rather than the light
# ones: on this white surface they clear every one of the six checks including
# contrast (the light steps put aqua/yellow/magenta below 3:1 and would leave a
# relief debt), which matters for hairline strokes in print.
#   node scripts/validate_palette.js \
#     "#3987e5,#d95926,#199e70,#c98500,#d55181" --mode light --surface "#FFFFFF"
#   -> lightness band PASS, chroma floor PASS,
#      CVD separation PASS (worst adjacent dE 8.4 protan, 8.7 tritan),
#      normal-vision floor PASS (worst adjacent dE 19.3), contrast PASS (all >= 3:1)
SERIES_COLOR = {
    "deepseek-chat": "#3987e5",       # slot 1 blue
    "deepseek-reasoner": "#d95926",   # slot 2 orange
    "gemini-3.1-flash": "#199e70",    # slot 3 aqua
    "gpt-4o-mini": "#c98500",         # slot 4 yellow
    "qwen3-8B": "#d55181",            # slot 5 magenta
}

# Hue is the primary identity channel, but this figure is printed and read in
# grayscale, where five hues collapse to five near-identical grays (worst
# grayscale L* gap 0.4). Marker shape, dash pattern and a direct label carry
# identity independently of color, so nothing here is encoded by color alone.
SERIES_MARKER = {
    "deepseek-chat": "o",
    "deepseek-reasoner": "s",
    "gemini-3.1-flash": "^",
    "gpt-4o-mini": "D",
    "qwen3-8B": "v",
}
SERIES_DASH = {
    "deepseek-chat": (0, ()),
    "deepseek-reasoner": (0, (3.6, 1.5)),
    "gemini-3.1-flash": (0, (1.3, 1.3)),
    "gpt-4o-mini": (0, (5.0, 1.4, 1.1, 1.4)),
    "qwen3-8B": (0, (2.4, 1.2)),
}

# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _num(raw: str | None) -> float | None:
    """Parse a CSV cell to float, mapping blanks and NaN to None.

    float('nan') is not None and NaN != NaN, so an explicit math.isnan guard is
    required -- a plain `if value` or `value is not None` test lets NaN through
    and silently poisons the mean.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return None if math.isnan(value) else value


def _macro(rows, column, transform=lambda x: x):
    """Macro mean over trajectories where `column` is defined, in percent.

    Returns (percent, n_defined). Exclusion is per-metric: a row dropped here
    for a blank p_verdict is still counted by a separate _macro on r_verdict.
    """
    values = [transform(v) for v in (_num(r[column]) for r in rows) if v is not None]
    if not values:
        return float("nan"), 0
    return 100.0 * sum(values) / len(values), len(values)


def _triple(rows):
    """(said-not-done, done-not-said, HAR, n_har) for a row subset, in percent."""
    said, _ = _macro(rows, "p_verdict", lambda x: 1.0 - x)
    done, _ = _macro(rows, "r_verdict", lambda x: 1.0 - x)
    har, n_har = _macro(rows, "har_verdict")
    return said, done, har, n_har


def _rounded_span(values):
    """Span as the reader computes it from a printed column: rounded endpoints.

    The existing appendix footnotes state e.g. "16.0 - 11.6 = 4.4 pp", i.e. the
    difference of the displayed one-decimal values, not of the raw means. Kept
    so the footnote stays checkable against the table above it.
    """
    r = [round(v, 1) for v in values]
    return round(max(r) - min(r), 1)


def load_rows():
    with CSV_PATH.open(newline="") as fh:
        return list(csv.DictReader(fh))


def compute(rows):
    keys = [k for k, _ in MODELS]

    per_model = {k: _triple([r for r in rows if r["model"] == k]) for k in keys}
    per_difficulty = {d: _triple([r for r in rows if r["difficulty"] == d])
                      for d in DIFFICULTIES}

    domains = sorted({r["domain"] for r in rows})
    per_domain = {d: _triple([r for r in rows if r["domain"] == d]) for d in domains}

    tasks_per_difficulty = {
        d: len({r["task_id"] for r in rows if r["difficulty"] == d}) for d in DIFFICULTIES
    }

    grid = {}
    for k in keys:
        for d in DIFFICULTIES:
            sub = [r for r in rows if r["model"] == k and r["difficulty"] == d]
            said, done, har, n_har = _triple(sub)
            grid[(k, d)] = {"har": har, "n_har": n_har, "n_traj": len(sub),
                            "said": said, "done": done}

    return {
        "per_model": per_model,
        "per_difficulty": per_difficulty,
        "per_domain": per_domain,
        "tasks_per_difficulty": tasks_per_difficulty,
        "grid": grid,
    }


def monotone_models(stats):
    """-> {model: 'increasing' | 'decreasing' | None} across the difficulty order.

    Reported honestly rather than used to select what gets drawn: the paper's
    claim is about the aggregate, so a single trending model qualifies the text,
    it does not get smoothed out of the figure.
    """
    out = {}
    for k, _ in MODELS:
        v = [stats["grid"][(k, d)]["har"] for d in DIFFICULTIES]
        if all(v[i] < v[i + 1] for i in range(len(v) - 1)):
            out[k] = "increasing"
        elif all(v[i] > v[i + 1] for i in range(len(v) - 1)):
            out[k] = "decreasing"
        else:
            out[k] = None
    return out


# --------------------------------------------------------------------------- #
# Plot helpers
# --------------------------------------------------------------------------- #


def _declutter(positions, min_gap, lo, hi):
    """Nudge label positions apart, preserving order, staying within [lo, hi]."""
    order = np.argsort(positions)
    out = np.array(positions, dtype=float)
    ordered = out[order]
    for i in range(1, len(ordered)):
        if ordered[i] - ordered[i - 1] < min_gap:
            ordered[i] = ordered[i - 1] + min_gap
    overflow = ordered[-1] - hi
    if overflow > 0:
        ordered -= overflow
    underflow = lo - ordered[0]
    if underflow > 0:
        ordered += underflow
    out[order] = ordered
    return out


def _strip(ax, keep=("bottom", "left")):
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)
        if side in keep:
            ax.spines[side].set_color(RULE)
            ax.spines[side].set_linewidth(0.6)


def draw_trends(ax, stats, top, label_x, x_hi):
    keys = [k for k, _ in MODELS]
    names = dict(MODELS)
    x = np.arange(len(DIFFICULTIES), dtype=float)

    ax.set_xlim(-0.16, x_hi)
    ax.set_ylim(0, top)

    # Gridlines drawn by hand so they stop before the direct-label gutter.
    for gy in np.arange(0, top + 1, 20):
        ax.plot([-0.16, x[-1] + 0.12], [gy, gy], color=GRID, linewidth=0.5, zorder=0)

    for k in keys:
        color = SERIES_COLOR[k]
        y = np.array([stats["grid"][(k, d)]["har"] for d in DIFFICULTIES])
        ax.plot(x, y, color=color, linewidth=1.0, linestyle=SERIES_DASH[k],
                zorder=3, solid_capstyle="round", dash_capstyle="round")
        for xi, d in zip(x, DIFFICULTIES):
            cell = stats["grid"][(k, d)]
            thin = cell["n_har"] < THIN_N
            ax.plot(
                [xi], [cell["har"]], linestyle="none", marker=SERIES_MARKER[k],
                markersize=3.4,
                # Filled cells get the surface ring so overlapping marks stay
                # separable; thin cells are hollow, which is the ring inverted.
                markerfacecolor=SURFACE if thin else color,
                markeredgecolor=color if thin else SURFACE,
                markeredgewidth=0.85 if thin else 0.7,
                zorder=4,
            )

    # Direct labels: identity never rests on hue alone (see the grayscale note).
    right_vals = [stats["grid"][(k, DIFFICULTIES[-1])]["har"] for k in keys]
    label_y = _declutter(right_vals, min_gap=0.085 * top, lo=0.0, hi=top)
    for k, ly, val in zip(keys, label_y, right_vals):
        ax.text(label_x, ly, names[k], ha="left", va="center",
                fontsize=5.9, color=TEXT, zorder=6)
        ax.plot([x[-1] + 0.06, label_x - 0.05], [val, ly],
                color="#CFCFCF", linewidth=0.45, zorder=2)

    # The one cell a sceptical reader will fixate on: the largest value in the
    # figure rests on two trajectories, so it is named rather than left to the
    # hollow-marker key.
    qwen = stats["grid"][("qwen3-8B", "comprehensive")]
    # Left of the marker at its own height: the series arrives steeply from
    # below-left, so anything placed under the point lands on the line.
    ax.text(
        x[-1] - 0.09, qwen["har"], f"n={qwen['n_har']}",
        ha="right", va="center", fontsize=5.4, color=MUTED, zorder=6,
    )

    ax.set_xticks(x)
    ax.set_xticklabels(DIFFICULTIES, fontsize=6.0)
    ax.set_yticks(np.arange(0, top + 1, 20))
    ax.tick_params(axis="x", length=2, width=0.5, color=RULE, pad=1.5)
    ax.tick_params(axis="y", length=2, width=0.5, color=RULE, labelsize=5.8, pad=1.5)
    # No x-axis label: the four tick labels are self-evidently difficulty levels
    # and the panel title names the axis, so the line would only cost height.
    ax.set_ylabel("HAR (%)", fontsize=6.6, color=TEXT, labelpad=2.0)
    ax.grid(False)
    _strip(ax, keep=("bottom", "left"))
    ax.spines["left"].set_bounds(0, top)
    ax.spines["bottom"].set_bounds(-0.16, x[-1] + 0.12)
    ax.set_title("(a) HAR by difficulty, one line per model", fontsize=7.2,
                 color=TEXT, pad=3.5)


def draw_spans(ax, stats, top):
    """The same claim as two spans, on the SAME y scale as panel (a).

    One shared scale, no second axis: the two spans are directly comparable to
    each other and to the vertical extent of the lines beside them.
    """
    keys = [k for k, _ in MODELS]

    model_vals = [stats["per_model"][k][2] for k in keys]
    diff_vals = [stats["per_difficulty"][d][2] for d in DIFFICULTIES]

    ax.set_xlim(-0.62, 1.62)
    ax.set_ylim(0, top)

    for gy in np.arange(0, top + 1, 20):
        ax.plot([-0.62, 1.62], [gy, gy], color=GRID, linewidth=0.5, zorder=0)

    specs = [
        (0.0, model_vals, [SERIES_COLOR[k] for k in keys], "across\nmodels"),
        (1.0, diff_vals, [MUTED] * len(diff_vals), "across\ndifficulty"),
    ]
    for xi, vals, colors, _ in specs:
        lo, hi = min(vals), max(vals)
        ax.plot([xi, xi], [lo, hi], color="#C9C9C9", linewidth=3.0,
                solid_capstyle="butt", zorder=2)
        for v, c in zip(vals, colors):
            ax.plot([xi - 0.15, xi + 0.15], [v, v], color=c, linewidth=1.1, zorder=4)
        ax.text(xi, hi + 0.030 * top, f"{_rounded_span(vals):.1f} pp",
                ha="center", va="bottom", fontsize=6.0, color=TEXT, zorder=6)

    ax.set_xticks([s[0] for s in specs])
    ax.set_xticklabels([s[3] for s in specs], fontsize=5.9, linespacing=1.15)
    ax.set_yticks(np.arange(0, top + 1, 20))
    ax.set_yticklabels([])
    ax.tick_params(axis="x", length=0, pad=2.5)
    ax.tick_params(axis="y", length=2, width=0.5, color=RULE)
    ax.grid(False)
    _strip(ax, keep=("bottom", "left"))
    ax.spines["left"].set_bounds(0, top)
    ax.spines["bottom"].set_bounds(-0.62, 1.62)
    ax.set_title("(b) HAR spread", fontsize=7.2, color=TEXT, pad=3.5)


def build(stats):
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

    ymax = max(stats["grid"][(k, d)]["har"] for k, _ in MODELS for d in DIFFICULTIES)
    # Ceil to a 10 so the axis stops just above the data; the 20-ticks below then
    # land on 0/20/40/60/80. Ceiling to a 20 would leave a fifth of the panel
    # empty, and height is the scarce resource here.
    top = 10 * math.ceil((ymax + 3) / 10)

    # Explicit rectangles, and savefig without bbox_inches="tight", so the
    # emitted canvas is exactly FIG_W x FIG_H -- one text column, no rescaling
    # in LaTeX (\includegraphics[width=\textwidth]).
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    ax_top, ax_h = 0.200, 0.638
    ax_a = fig.add_axes([0.070, ax_top, 0.655, ax_h])
    ax_b = fig.add_axes([0.812, ax_top, 0.150, ax_h])

    draw_trends(ax_a, stats, top, label_x=3.28, x_hi=4.32)
    draw_spans(ax_b, stats, top)

    fig.text(
        0.070, 0.022,
        f"Odoo only (AppWorld carries no difficulty labels).  "
        f"Hollow markers: fewer than {THIN_N} trajectories with a defined HAR.",
        ha="left", va="bottom", fontsize=5.4, color=MUTED,
    )
    return fig


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #

_TABLE_NOTE = """% [H]: appendix-only table, placed exactly where it is written so that it
% follows the section heading and its lead-in sentence.  If this table ever
% moves back into the main text, restore [t].
"""


def domain_table(stats):
    rows = sorted(stats["per_domain"].items(), key=lambda kv: -kv[1][2])
    body = "\n".join(
        f"{name:<16} & {said:.1f} & {done:.1f} & {har:.1f} \\\\"
        for name, (said, done, har, _) in rows
    )
    hars = [v[2] for _, v in rows]
    gaps = [round(v[1], 1) - round(v[0], 1) for _, v in rows]
    return f"""{_TABLE_NOTE}\\begin{{table}}[H]
\\centering
\\caption{{Per-domain halluci-action rates on Odoo, pooled across models (\\%).
Odoo only: AppWorld labels its tasks with a disjoint app taxonomy
(\\texttt{{gmail}}, \\texttt{{venmo}}, \\texttt{{spotify}}, \\ldots) that these business
domains do not span, so the two are not poolable.}}
\\label{{tab:har-by-domain}}
\\begin{{tabular}}{{l c c c}}
\\toprule
\\textbf{{Domain}} & \\textbf{{Said-not-done}} & \\textbf{{Did-not-said}} & \\textbf{{HAR}} \\\\
\\midrule
{body}
\\bottomrule
\\end{{tabular}}

\\vspace{{3pt}}
\\raggedright
\\footnotesize Macro-averaged over trajectories, with a trajectory excluded from a
metric only where that metric is undefined. HAR range: ${min(hars):.1f}$--${max(hars):.1f}\\%$
(spread ${_rounded_span(hars):.1f}$~pp). The reverse gap exceeds the forward gap in every
domain: silent actions dominate over-claiming by ${min(gaps):.1f}$--${max(gaps):.1f}$~pp.
\\end{{table}}
"""


def complexity_table(stats):
    body = "\n".join(
        "{:<14} & {:>2d} & {:.1f} & {:.1f} & {:.1f} \\\\".format(
            d, stats["tasks_per_difficulty"][d], *stats["per_difficulty"][d][:3]
        )
        for d in DIFFICULTIES
    )
    hars = [stats["per_difficulty"][d][2] for d in DIFFICULTIES]
    hi = DIFFICULTIES[int(np.argmax(hars))]
    lo = DIFFICULTIES[int(np.argmin(hars))]
    return f"""{_TABLE_NOTE}\\begin{{table}}[H]
\\centering
\\caption{{Per-complexity-level halluci-action rates on Odoo, pooled across models (\\%).
AppWorld is excluded: its tasks carry no difficulty labels.}}
\\label{{tab:har-by-complexity}}
\\begin{{tabular}}{{l r c c c}}
\\toprule
\\textbf{{Difficulty}} & \\textbf{{Tasks}} & \\textbf{{Said-not-done}} & \\textbf{{Did-not-said}} & \\textbf{{HAR}} \\\\
\\midrule
{body}
\\bottomrule
\\end{{tabular}}

\\vspace{{3pt}}
\\raggedright
\\footnotesize Macro-averaged over trajectories, with a trajectory excluded from a
metric only where that metric is undefined. HAR range: ${min(hars):.1f}$--${max(hars):.1f}\\%$
(spread ${_rounded_span(hars):.1f}$~pp), against ${_rounded_span([stats['per_model'][k][2] for k, _ in MODELS]):.1f}$~pp
across models. HAR does not rise with difficulty---it is highest at \\emph{{{hi}}} and
lowest at \\emph{{{lo}}}, so task complexity is not the driver of halluci-action.
\\end{{table}}
"""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> None:
    rows = load_rows()
    stats = compute(rows)
    keys = [k for k, _ in MODELS]

    print(f"source: {CSV_PATH}  ({len(rows)} trajectories, Odoo only)\n")

    print("-- per model x difficulty, HAR % (n defined / n trajectories) --")
    header = f"{'model':21s}" + "".join(f"{d:>21s}" for d in DIFFICULTIES) + "   monotone?"
    print(header)
    mono = monotone_models(stats)
    for k in keys:
        cells = []
        for d in DIFFICULTIES:
            c = stats["grid"][(k, d)]
            cells.append(f"{c['har']:8.1f} (n={c['n_har']:2d}/{c['n_traj']:2d})")
        print(f"{k:21s}" + "".join(f"{c:>21s}" for c in cells)
              + f"   {mono[k] or 'no'}")

    print("\n-- per model, pooled over difficulty --")
    for k in keys:
        said, done, har, n = stats["per_model"][k]
        print(f"{k:21s} said={said:5.1f} done={done:5.1f} HAR={har:5.1f}  n_har={n}")

    print("\n-- per difficulty, pooled over models --")
    for d in DIFFICULTIES:
        said, done, har, n = stats["per_difficulty"][d]
        print(f"{d:21s} tasks={stats['tasks_per_difficulty'][d]:2d} "
              f"said={said:5.1f} done={done:5.1f} HAR={har:5.1f}  n_har={n}")

    print("\n-- per domain, pooled over models (HAR desc) --")
    for name, (said, done, har, n) in sorted(stats["per_domain"].items(),
                                             key=lambda kv: -kv[1][2]):
        print(f"{name:21s} said={said:5.1f} done={done:5.1f} HAR={har:5.1f}  n_har={n}")

    model_h = [stats["per_model"][k][2] for k in keys]
    diff_h = [stats["per_difficulty"][d][2] for d in DIFFICULTIES]
    dom_h = [v[2] for v in stats["per_domain"].values()]
    print("\n-- spans (rounded-endpoint convention | unrounded) --")
    for label, vals in (("across models", model_h), ("across difficulty", diff_h),
                        ("across domains", dom_h)):
        print(f"{label:21s} {_rounded_span(vals):5.1f} pp | {max(vals) - min(vals):6.3f} pp")

    trending = [k for k in keys if mono[k]]
    print("\n-- monotone across the difficulty order --")
    if trending:
        for k in trending:
            print(f"  {k}: {mono[k]}")
    else:
        print("  none")
    rising = [k for k in trending if mono[k] == "increasing"]
    print(f"  monotonically RISING with difficulty: {', '.join(rising) or 'none'}")

    fig = build(stats)
    fig_targets = [OUT_DIR / "har_by_difficulty.png", OUT_DIR / "har_by_difficulty.pdf"]
    if LATEX_FIG_DIR.is_dir():
        fig_targets.append(LATEX_FIG_DIR / "har_by_difficulty.png")

    print()
    for path in fig_targets:
        # No bbox_inches="tight": the canvas must stay exactly FIG_W x FIG_H.
        kwargs = {"dpi": 400} if path.suffix == ".png" else {}
        fig.savefig(path, **kwargs)
        print(f"wrote {path}")
    plt.close(fig)

    tables = {"HAR_by_domain.tex": domain_table(stats),
              "HAR_by_complexity.tex": complexity_table(stats)}
    for name, text in tables.items():
        for directory in (d for d in (LATEX_TAB_DIR,) if d.is_dir()):
            (directory / name).write_text(text)
            print(f"wrote {directory / name}")


if __name__ == "__main__":
    main()
