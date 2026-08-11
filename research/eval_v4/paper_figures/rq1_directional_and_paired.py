#!/usr/bin/env python3
"""RQ1 figure: directional halluci-action gaps in two environments + paired HAR.

Panels
------
(a) Odoo      diverging bars, said-not-done (left) vs done-not-said (right)
(b) AppWorld  same, on the SAME x scale as (a) so the two are comparable
(c) HAR per model at both environments, one line per model

Aggregation (must match the paper text)
---------------------------------------
Macro averaging over trajectories, verdict definition. A trajectory is excluded
from a metric when that metric is undefined (blank / NaN); exclusion is
per-metric, not listwise, so a trajectory with a defined r_verdict but a blank
p_verdict still contributes to done-not-said.

    said-not-done = mean_traj(1 - p_verdict)
    done-not-said = mean_traj(1 - r_verdict)
    HAR           = mean_traj(har_verdict)

Severity subsets are macro-averaged on the *same* per-trajectory filter as the
bar they nest inside, so each is a genuine subset of its bar:

    required-action misses  = mean over p_verdict-defined trajs of
                              required_miss / n_claims
    undisclosed forbidden   = mean over r_verdict-defined trajs of
                              covert / n_actions

Regenerate after the AppWorld batch grows:  python rq1_directional_and_paired.py
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from matplotlib.patches import Patch

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[2]                      # .../research/eval_v4/paper_figures -> repo
DATA_DIR = REPO_ROOT / "research" / "appworld_backend"

CSVS = {
    "Odoo": DATA_DIR / "har_trajectories_odoo.csv",
    "AppWorld": DATA_DIR / "har_trajectories_appworld.csv",
}

# Extra copy destination (the LaTeX tree). Skipped silently if absent.
LATEX_FIG_DIR = Path("/Users/maokaifang/Downloads/iclr/iclr2026/figures")

ENVS = ["Odoo", "AppWorld"]

# Full text width of the ICLR two-column-free single-column body, in inches.
# Vertical space is the scarce resource, so the height is the minimum that keeps
# 5 rows per panel and 5.6pt value labels legible in print.
FIG_W, FIG_H = 5.5, 2.05

# Display order + display names, as they appear in the paper's table.
MODELS = [
    ("deepseek-chat", "deepseek-chat"),
    ("deepseek-reasoner", "deepseek-reasoner"),
    ("gemini-3.1-flash", "gemini-3.1-flash"),
    ("gpt-4o-mini", "gpt-4o-mini"),
    ("qwen3-8B", "qwen3-8B"),
]

# Cells whose severity value is inflated by a known measurement artifact:
# gpt-4o-mini's AppWorld trajectories contain degenerate retry loops (one cell
# issues 123 calls with only 10 distinct tool+parameter pairs) and 70.6% of its
# steps carry empty assistant text, which makes every action in those steps
# undisclosed by construction.
#
# These are drawn as ordinary solid segments and labelled on the same rule as
# every other severe subset -- the value is real under this figure's
# aggregation. They carry a superscript asterisk, and nothing else: the full
# account lives in the appendix's "Measurement caveats" section, which the
# caption points to. Do not remove the mark; without it the segment reads as a
# behavioural finding (an agent concealing several times more policy violations
# than any other), which is exactly what it is not.
ARTIFACT_CELLS = {("AppWorld", "gpt-4o-mini", "action")}

# --------------------------------------------------------------------------- #
# Style
# --------------------------------------------------------------------------- #

CLAIM_PALE = "#C2D8E9"   # said-not-done, full gap
CLAIM_CORE = "#15689F"   # said-not-done, severe subset
ACTION_PALE = "#EFC8BB"  # done-not-said, full gap
ACTION_CORE = "#B85B47"  # done-not-said, severe subset

# Panel (c) is an emphasis encoding, not a categorical palette: the four stable
# models recede to one gray, the single large mover is picked out in ink.
STABLE = "#8A8A8A"
MOVER = "#2F2F2F"

VAL_FS = 5.6        # bar-end gap values
SEV_FS = 5.3        # severe-subset values
NAME_FS_AB = 6.6    # model names on panel (a)
NAME_FS_C = 5.9     # model names in panel (c)'s gutter
AST_FS = 5.0        # superscript mark on a flagged segment
SEV_LABEL_MIN = 2.0  # below this a severe subset is left unlabelled

TEXT = "#333333"
MUTED = "#777777"
GRID = "#E6E6E6"
BAND = "#F2F0EC"         # row band marking a direction reversal
SURFACE = "#FFFFFF"

# CLAIM_CORE / ACTION_CORE pass all six checks of the dataviz validator on a
# white surface (CVD deltaE 14.7 protan, normal-vision 24.5, both >= 3:1).

# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _num(raw: str | None) -> float | None:
    """Parse a CSV cell to float, mapping blanks and NaN to None.

    float('nan') is not None and NaN != NaN, so an explicit math.isnan guard is
    required -- a plain `if value` or `value is not None` test lets NaN through.
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
    """Macro mean over trajectories where `column` is defined, in percent."""
    values = [transform(v) for v in (_num(r[column]) for r in rows) if v is not None]
    if not values:
        return float("nan"), 0
    return 100.0 * sum(values) / len(values), len(values)


def _macro_ratio(rows, gate, numerator, denominator):
    """Macro mean of numerator/denominator over trajectories where `gate` is defined.

    Trajectories with a zero/undefined denominator contribute 0 rather than
    being dropped, so the result stays on the same denominator (the same
    trajectory set) as the bar it nests inside and is a true subset of it.
    """
    kept = [r for r in rows if _num(r[gate]) is not None]
    if not kept:
        return float("nan")
    total = 0.0
    for r in kept:
        den = _num(r[denominator])
        if den:
            total += (_num(r[numerator]) or 0.0) / den
    return 100.0 * total / len(kept)


def load_stats():
    """-> {env: {model_key: {metric: value}}}, all rates in percent."""
    stats = {}
    for env, path in CSVS.items():
        with path.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
        per_model = {}
        for key, _ in MODELS:
            sub = [r for r in rows if r["model"] == key]
            said, n_p = _macro(sub, "p_verdict", lambda x: 1.0 - x)
            done, n_r = _macro(sub, "r_verdict", lambda x: 1.0 - x)
            har, n_h = _macro(sub, "har_verdict")
            per_model[key] = {
                "said_not_done": said,
                "done_not_said": done,
                "har": har,
                "required_miss": _macro_ratio(sub, "p_verdict", "required_miss", "n_claims"),
                "covert": _macro_ratio(sub, "r_verdict", "covert", "n_actions"),
                "n_traj": len(sub),
                "n_p": n_p,
                "n_r": n_r,
                "n_har": n_h,
            }
        stats[env] = per_model
    return stats


def flipped_models(stats):
    """Models whose dominant direction reverses between the two environments."""
    out = []
    for key, _ in MODELS:
        dom = [
            "said" if stats[e][key]["said_not_done"] > stats[e][key]["done_not_said"] else "done"
            for e in ENVS
        ]
        if dom[0] != dom[1]:
            out.append(key)
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


def _strip(ax, keep_bottom=True, keep_left=False):
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(
            (side == "bottom" and keep_bottom) or (side == "left" and keep_left)
        )
    for side in ("bottom", "left"):
        if ax.spines[side].get_visible():
            ax.spines[side].set_color("#B0B0B0")
            ax.spines[side].set_linewidth(0.6)


def _text_w_in(fig, s, fontsize, weight="normal"):
    """Width of a string in inches, from the real renderer -- so gutters are
    sized to what the text actually needs instead of a guess."""
    t = fig.text(0.0, 0.0, s, fontsize=fontsize, fontweight=weight)
    width = t.get_window_extent(renderer=fig.canvas.get_renderer()).width / fig.dpi
    t.remove()
    return width


def draw_diverging(ax, env, stats, xlim, show_names, flips, panel_label, fig, ax_w_in):
    keys = [k for k, _ in MODELS]
    names = [n for _, n in MODELS]
    y = np.arange(len(keys))
    bar_h = 0.46

    said = np.array([stats[env][k]["said_not_done"] for k in keys])
    done = np.array([stats[env][k]["done_not_said"] for k in keys])
    req = np.array([stats[env][k]["required_miss"] for k in keys])
    cov = np.array([stats[env][k]["covert"] for k in keys])

    # Geometry in data units, measured per label rather than assumed.
    upi = (xlim[1] - xlim[0]) / ax_w_in          # data units per inch
    pad = 0.030 * upi
    core_pad = 0.016 * upi

    def w_u(s, fontsize):
        return _text_w_in(fig, s, fontsize) * upi

    # Row bands behind everything: dominant direction reverses across envs.
    for i, k in enumerate(keys):
        if k in flips:
            ax.axhspan(i - 0.44, i + 0.44, color=BAND, zorder=0, linewidth=0)

    ax.xaxis.grid(True, color=GRID, linewidth=0.5, zorder=1)
    ax.set_axisbelow(False)

    # Full gaps (pale), then severe subsets (core) nested against the zero line.
    ax.barh(y, -said, height=bar_h, color=CLAIM_PALE, edgecolor="none", zorder=2)
    ax.barh(y, done, height=bar_h, color=ACTION_PALE, edgecolor="none", zorder=2)

    SIDES = (("claim", -1, CLAIM_CORE), ("action", +1, ACTION_CORE))

    for i, k in enumerate(keys):
        for side, sign, core_colour in SIDES:
            total = (done if sign > 0 else said)[i]
            core = (cov if sign > 0 else req)[i]
            artifact = (env, k, side) in ARTIFACT_CELLS
            out, inn = ("left", "right") if sign > 0 else ("right", "left")

            # ---- the severe-subset core -----------------------------------
            # Every core is a solid segment, flagged or not: the value is real
            # under this figure's aggregation, so it is drawn like one. The
            # caveat rides on the asterisk added below, not on the fill.
            ax.barh(i, sign * core, height=bar_h, color=core_colour,
                    edgecolor="none", zorder=3)
            # Surface gap at the boundary so the core's end reads crisply
            # against the pale remainder instead of fading into it.
            if 0.8 < core < total - 0.4:
                ax.plot([sign * core] * 2, [i - bar_h / 2, i + bar_h / 2],
                        color=SURFACE, linewidth=1.0, solid_capstyle="butt",
                        zorder=3.5)

            # ---- where each label can go ----------------------------------
            lbl_t = f"{total:.1f}"
            w_t = w_u(lbl_t, VAL_FS)
            # Long bars carry their value inside; that is what lets the shared
            # scale tighten to the longest bar rather than bar + label.
            end_inside = total >= w_t + 2 * pad

            # The core fills the bar, so the bar-end label already *is* the
            # severity value -- recolour it rather than printing it twice.
            nearly_full = core >= SEV_LABEL_MIN and total - core < 1.0

            # A flagged cell is labelled on the same rule as every other one; it
            # only reserves a little extra room for the trailing asterisk.
            ast_w = w_u("*", AST_FS) + 0.4 * pad if artifact else 0.0

            sev = None
            if core >= SEV_LABEL_MIN and not nearly_full:
                lbl_s = f"{core:.1f}"
                w_s = w_u(lbl_s, SEV_FS)
                if core >= w_s + ast_w + 2 * core_pad:
                    # Big enough to hold its own number, on the core itself.
                    sev = (sign * (core - core_pad), inn, SURFACE, lbl_s, w_s)
                else:
                    # Otherwise just past the boundary, into the pale remainder,
                    # keeping clear of an inside bar-end label.
                    free_to = total - (w_t + 2 * pad) if end_inside else total - pad
                    if free_to - core >= w_s + ast_w + pad:
                        sev = (sign * (core + pad), out, core_colour, lbl_s, w_s)

            if sev is not None:
                x, ha, colour, text, w_s = sev
                ax.text(x, i, text, ha=ha, va="center", color=colour,
                        fontsize=SEV_FS, zorder=6)

            x_end = sign * (total - pad) if end_inside else sign * (total + pad)
            ax.text(x_end, i, lbl_t, ha=inn if end_inside else out, va="center",
                    color=core_colour if nearly_full else TEXT,
                    fontsize=VAL_FS, zorder=6)

            if artifact:
                # Superscript mark on the flagged segment. The caveat itself
                # lives in the appendix ("Measurement caveats"), which the
                # caption points to -- the figure carries only the mark, so it
                # cannot be read as a clean behavioural finding.
                if sev is not None:
                    x_ast = sev[0] + (w_s if sev[1] == out else 0.0) * sign
                elif nearly_full:
                    x_ast = x_end + (w_t if not end_inside else 0.0) * sign
                else:
                    x_ast = sign * core
                # Times sets the asterisk high in the em box already, so it needs
                # only a small raise -- more reads as detached rather than as a
                # superscript on the value.
                ax.text(x_ast + sign * 0.04 * pad, i - 0.085, "*", ha=out,
                        va="center", color=core_colour, fontsize=AST_FS, zorder=6)

    ax.axvline(0, color="#8A8A8A", linewidth=0.7, zorder=4)

    ax.set_xlim(*xlim)
    ax.set_ylim(len(keys) - 0.5, -0.5)

    half = xlim[1]
    ticks = [-half, -half / 2, 0, half / 2, half]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{abs(t):g}" for t in ticks], fontsize=5.8)
    ax.set_yticks(y)
    if show_names:
        ax.set_yticklabels(names, fontsize=NAME_FS_AB)
    else:
        ax.set_yticklabels([])
    ax.tick_params(axis="y", length=0, pad=3)
    ax.tick_params(axis="x", length=2, width=0.5, color="#B0B0B0", pad=1.5)
    ax.yaxis.grid(False)
    _strip(ax)

    ax.set_title(f"({panel_label}) {env}", fontsize=7.2, color=TEXT, pad=3.5)


def draw_paired(ax, stats, panel_label, fig, ax_w_in):
    """Slope chart. Emphasis encoding: the four near-flat models recede to one
    gray, the single large mover is picked out in ink. Only the mover carries
    numeric labels -- the honest reading is 'mostly stable, one large mover',
    not a claim about rank order, so the rest read off the axis."""
    keys = [k for k, _ in MODELS]
    names = [n for _, n in MODELS]
    har = {k: [stats[e][k]["har"] for e in ENVS] for k in keys}

    moves = {k: abs(har[k][1] - har[k][0]) for k in keys}
    mover = max(moves, key=moves.get)

    x = np.array([0.0, 1.0])
    ymax = max(max(v) for v in har.values())
    top = 5 * math.ceil((ymax + 3) / 5)

    # The model-name gutter lives INSIDE the axes and the value axis moves to the
    # right, so nothing overhangs and the saved canvas stays exactly 5.5in wide.
    # Its width is measured from the longest name -- no more reserved than needed,
    # which is what keeps the slope region wide.
    x_hi = 1.10
    lead_in, pad_in = 0.042, 0.014
    # Measured at the weight each name is actually drawn in -- only the mover is
    # bold, and it is not the longest name, so assuming bold would over-reserve.
    gutter_in = lead_in + pad_in + max(
        _text_w_in(fig, n, NAME_FS_C, "bold" if k == mover else "normal")
        for k, n in zip(keys, names)
    )
    frac = gutter_in / ax_w_in
    x_lo = -(x_hi * frac / (1.0 - frac))
    upi = (x_hi - x_lo) / ax_w_in
    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(0, top)

    name_x = -lead_in * upi
    lead_a, lead_b = -lead_in * 0.88 * upi, -0.012 * upi

    # Gridlines drawn by hand so they stop before the label gutter.
    for gy in np.arange(0, top + 1, 10):
        ax.plot([lead_b * 1.4, x_hi], [gy, gy], color=GRID, linewidth=0.5, zorder=0)

    for k in keys:
        is_mover = k == mover
        ax.plot(
            x, har[k],
            color=MOVER if is_mover else STABLE,
            linewidth=1.5 if is_mover else 0.9,
            zorder=4 if is_mover else 3,
            solid_capstyle="round",
        )
        ax.plot(
            x, har[k], linestyle="none", marker="o",
            markersize=4.0 if is_mover else 2.8,
            color=MOVER if is_mover else STABLE,
            markeredgecolor=SURFACE, markeredgewidth=0.7,   # surface ring on overlap
            zorder=5 if is_mover else 3,
        )

    # Direct labels on the Odoo side, where the five values are well separated.
    left_vals = [har[k][0] for k in keys]
    label_y = _declutter(left_vals, min_gap=0.058 * top, lo=0.0, hi=top)
    for k, name, ly, val in zip(keys, names, label_y, left_vals):
        is_mover = k == mover
        ax.text(
            name_x, ly, name, ha="right", va="center",
            fontsize=NAME_FS_C, color=TEXT if is_mover else MUTED,
            fontweight="bold" if is_mover else "normal", zorder=6,
        )
        # Leader from the (possibly nudged) label back to its marker.
        ax.plot([lead_a, lead_b], [ly, val], color="#CFCFCF", linewidth=0.45, zorder=2)

    # Selective values: only the one series that matters carries numbers. The
    # AppWorld end sits *below* its marker -- the two lines it lands between
    # converge from above, so below is the only clear side.
    ax.text(0.05, har[mover][0] + 0.015 * top, f"{har[mover][0]:.1f}", ha="left",
            va="bottom", fontsize=5.9, color=MOVER, zorder=6)
    ax.text(1.0, har[mover][1] - 0.045 * top, f"{har[mover][1]:.1f}", ha="center",
            va="top", fontsize=5.9, color=MOVER, zorder=6)

    ax.set_xticks(x)
    ax.set_xticklabels(ENVS, fontsize=6.4)
    ax.tick_params(axis="x", length=2, width=0.5, color="#B0B0B0", pad=1.5)
    ax.set_yticks(np.arange(0, top + 1, 10))
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.tick_params(axis="y", length=2, width=0.5, color="#B0B0B0", labelsize=5.8, pad=1.5)
    ax.set_ylabel("HAR (%)", fontsize=6.6, color=TEXT, labelpad=2.5, rotation=90)
    ax.xaxis.grid(False)
    ax.yaxis.grid(False)
    for side in ("top", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["right"].set_visible(True)
    ax.spines["right"].set_color("#B0B0B0")
    ax.spines["right"].set_linewidth(0.6)
    ax.spines["right"].set_bounds(0, top)

    ax.set_title(f"({panel_label}) HAR, paired", fontsize=7.2, color=TEXT, pad=3.5)
    return mover


# --------------------------------------------------------------------------- #
# Figure
# --------------------------------------------------------------------------- #


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

    flips = flipped_models(stats)

    # Explicit rectangles, and savefig without bbox_inches="tight", so the
    # emitted canvas is exactly FIG_W x FIG_H -- one text column, no rescaling
    # in LaTeX (\includegraphics[width=\textwidth]).
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    ax_top, ax_h = 0.198, 0.622

    # The name column keeps only what the longest name measures, and (a)/(b)
    # split everything left over.
    names = [n for _, n in MODELS]
    left = (max(_text_w_in(fig, n, NAME_FS_AB) for n in names) + 0.055) / FIG_W
    # The gap must clear the two outermost tick labels, which straddle the panel
    # edges (half of "40" overhangs on each side).
    ab_right, gap_ab = 0.652, 0.032
    w_ab = (ab_right - left - gap_ab) / 2
    c_left, c_right = 0.672, 0.952

    ax_a = fig.add_axes([left, ax_top, w_ab, ax_h])
    ax_b = fig.add_axes([left + w_ab + gap_ab, ax_top, w_ab, ax_h])
    ax_c = fig.add_axes([c_left, ax_top, c_right - c_left, ax_h])

    # ONE shared x scale across (a) and (b) -- the comparison is the point.
    # Bar-end labels sit inside long bars, so the limit only has to clear the
    # longest bar itself rather than bar + label.
    span = max(
        max(stats[e][k][m] for e in ENVS for k, _ in MODELS)
        for m in ("said_not_done", "done_not_said")
    )
    lim = 10 * math.ceil((span + 2) / 10)
    xlim = (-lim, lim)

    ab_w_in = w_ab * FIG_W
    draw_diverging(ax_a, "Odoo", stats, xlim, True, flips, "a", fig, ab_w_in)
    draw_diverging(ax_b, "AppWorld", stats, xlim, False, flips, "b", fig, ab_w_in)
    mover = draw_paired(ax_c, stats, "c", fig, (c_right - c_left) * FIG_W)

    # Direction key: one centred line over the (a)+(b) span, so it reads as a
    # key for BOTH panels rather than as a label on either one of them.
    ab_left = ax_a.get_position().x0
    ab_right = ax_b.get_position().x1
    ab_mid = (ab_left + ab_right) / 2
    fig.text(
        ab_mid - 0.012, 0.948, "←  said-not-done", ha="right", va="center",
        fontsize=7.0, color=CLAIM_CORE, fontweight="bold",
    )
    fig.text(ab_mid, 0.948, "·", ha="center", va="center", fontsize=7.0, color=MUTED)
    fig.text(
        ab_mid + 0.012, 0.948, "done-not-said  →", ha="left", va="center",
        fontsize=7.0, color=ACTION_CORE, fontweight="bold",
    )

    fig.text(
        ab_mid, 0.098, "mean over trajectories (%)", ha="center", va="center",
        fontsize=6.6, color=TEXT,
    )

    legend = fig.legend(
        handles=[
            Patch(facecolor="#D5D5D5", edgecolor="none", label="directional gap"),
            Patch(facecolor="#6E6E6E", edgecolor="none", label="severe subset"),
            Patch(facecolor=BAND, edgecolor="#CBC7BF", linewidth=0.5,
                  label="dominant direction reverses"),
        ],
        loc="lower center", bbox_to_anchor=(ab_mid, 0.000), ncol=3,
        frameon=False, fontsize=5.9, handlelength=1.15, handleheight=0.8,
        columnspacing=0.9, handletextpad=0.32,
    )
    for text in legend.get_texts():
        text.set_color(TEXT)

    return fig, flips, mover


def main() -> None:
    stats = load_stats()

    # Console readout, for diffing against the paper's table.
    print(f"{'env':9s} {'model':20s} {'said':>6s} {'done':>6s} {'HAR':>6s} "
          f"{'reqmiss':>8s} {'covert':>7s}   n(p/r/har)")
    for env in ENVS:
        for key, _ in MODELS:
            s = stats[env][key]
            print(f"{env:9s} {key:20s} {s['said_not_done']:6.1f} {s['done_not_said']:6.1f} "
                  f"{s['har']:6.1f} {s['required_miss']:8.1f} {s['covert']:7.1f}   "
                  f"{s['n_p']}/{s['n_r']}/{s['n_har']} of {s['n_traj']}")

    fig, flips, mover = build(stats)
    print(f"\ndirection reverses across environments: {', '.join(flips) or 'none'}")
    print(f"largest HAR move: {mover}")

    targets = [OUT_DIR / "rq1_directional_and_paired.png",
               OUT_DIR / "rq1_directional_and_paired.pdf"]
    if LATEX_FIG_DIR.is_dir():
        targets.append(LATEX_FIG_DIR / "rq1_directional_and_paired.png")

    for path in targets:
        # No bbox_inches="tight": the canvas must stay exactly FIG_W x FIG_H.
        kwargs = {}
        if path.suffix == ".png":
            kwargs["dpi"] = 400
        fig.savefig(path, **kwargs)
        print(path)
    plt.close(fig)


if __name__ == "__main__":
    main()
