#!/usr/bin/env python3
"""Figure: HAR by model x task domain, one panel per environment.

Shape
-----
Two stacked panels sharing the model row axis, because the two environments have
DISJOINT domain taxonomies -- Odoo labels tasks with ten business domains, AppWorld
with app names (gmail, venmo, spotify, ...). They cannot share an x axis, and
pooling them into one would invent a taxonomy neither benchmark has. What the two
DO share is the five models, so the row axis is shared and the column axis is not.

    (a) Odoo      5 models x 10 business domains
    (b) AppWorld  5 models x  9 apps

Columns within each panel are ordered by pooled HAR, descending left to right, so
the column marginal is legible as a left-to-right gradient without a marginal row.

Aggregation (must match the paper text and the main results table)
------------------------------------------------------------------
Macro averaging over trajectories, verdict definition. A trajectory is excluded
from a metric when that metric is undefined (blank / NaN); exclusion is PER-METRIC,
not listwise. float('nan') is not None and NaN != NaN, so the blank test is an
explicit math.isnan guard -- a plain truth test lets NaN through and silently
poisons the mean.

    HAR(cell) = mean over trajectories in that cell with a defined har_verdict

Verified against the published marginals before plotting:
    Odoo per model    3.3 / 4.2 / 16.1 / 32.1 / 45.9
    Odoo per domain   inventory 20.9 ... pos 9.4
    AppWorld per model 7.3 / 4.8 / 18.2 / 32.2 / 18.0
`main` re-derives all three and asserts them, so a data refresh that moves a
marginal fails loudly here rather than shipping a figure that disagrees with the
table two pages earlier.

Colour: DIVERGING, centred on a declared reference of 15%
---------------------------------------------------------
Blue below the reference, red above it, white at it. Two objections to a diverging
scheme were raised and each is answered rather than waved off:

  * A sample-derived centre (e.g. the pooled mean) would make the same cell value
    change colour on a data refresh, so "blue" would mean "below whatever we
    happened to measure". The centre here is therefore NOT derived from the data:
    CENTER is a fixed, declared 15%. It is round, it sits beside both pooled HARs
    (15.92 Odoo, 15.95 AppWorld) without being either, and it splits the 95 drawn
    cells 50 below / 45 above. A refresh moves cells across the boundary; it does
    not move the boundary. Stated on the colourbar and in the footnote so it reads
    as a declared level rather than a discovered one.
  * Grayscale ordering IS genuinely lost, and that is the accepted cost. A
    diverging ramp is deliberately non-monotone in lightness -- light at the centre,
    dark at both ends -- so in grayscale a 3% cell and a 45% cell print as similar
    grays. The mitigation is that every cell already prints its value: grayscale
    costs the at-a-glance ordering, not the data. Nothing is added to compensate.

The arms are UNEQUAL by construction: 15 points of range below the centre against
45 above, via TwoSlopeNorm. A colour step therefore means three times as much HAR
on the red side as on the blue side, which the footnote states. Equalising the arms
would compress the top of the range -- exactly the cells the figure exists to show
-- so the asymmetry is kept and declared. The colourbar is drawn linear in VALUE,
which puts the white reference a quarter of the way up and makes the asymmetry
visible rather than merely footnoted.

Hues stay inside the paper's identity: the blue arm in the family of #1F5C99 (the
"what the user sees" blue of Figure 1), the red arm in the family of the warm
#B3590A, near-white at the centre so the reference reads as neutral. Because both
arms end dark, cell-label ink is chosen per cell by whichever of dark/white has the
better contrast against that cell, and `check_label_contrast` reports the
worst case across every drawn cell rather than leaving it to the eye.

One scale, one centre, one vmax, shared by both panels, so a colour means the same
thing in each.

Thin cells
----------
This is the main hazard in this figure and it is marked, not smoothed. Per-cell
counts of HAR-defined trajectories are median 6 (min 1) on Odoo and median 12
(min 3) on the AppWorld columns that survive. A cell resting on 1 trajectory must
not read like a cell resting on 20.

  * Cells with fewer than THIN_N defined trajectories are hatched and carry their
    n inside the cell. Fourteen of the fifty Odoo cells qualify; three of the
    AppWorld cells do.
  * The `supervisor` app and the empty-string domain are dropped: the empty-string
    domain has 14 trajectories and ZERO with a defined HAR, and `supervisor` has a
    single trajectory in a single cell (qwen3-8B, 33.3) with its other four cells
    empty. Neither is a column; both are recorded in the footnote and in stdout.
    NOTE for the author: the brief named `todoist` as the unpopulated AppWorld
    column. It is not -- todoist holds 40 defined trajectories across all five
    cells (6-10 each) and is kept. The column meant was `supervisor`.
  * Colour is clipped at VMAX; the one cell above it (qwen3-8B x inventory,
    100.0 on n=3) prints its value and is hatched, so nothing is hidden.

Every cell carries its printed HAR, so the number, not the hue, is the primary
channel -- which is the right ranking when some cells are this thin.

Regenerate:  python har_model_by_domain.py
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm, to_rgb
from matplotlib.patches import Rectangle

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[2]                     # research/eval_v4/paper_figures -> repo
DATA_DIR = REPO_ROOT / "research" / "appworld_backend"

CSV_PATHS = {
    "odoo": DATA_DIR / "har_trajectories_odoo.csv",
    "appworld": DATA_DIR / "har_trajectories_appworld.csv",
}

# Extra copy destination (the LaTeX tree). Skipped silently if absent.
LATEX_FIG_DIR = Path("/Users/maokaifang/Downloads/iclr/iclr2026/figures")

# One text column wide. Height is the scarce resource -- the submission is over
# its page limit -- so the panels are as short as 5 legible rows and a rotated
# domain axis allow, and the colourbar is vertical (it costs width, not height).
FIG_W, FIG_H = 5.5, 2.96

# Display order = ascending pooled Odoo HAR, matching har_by_difficulty.py so the
# model column reads identically across the paper's figures.
MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
    "gemini-3.1-flash",
    "gpt-4o-mini",
    "qwen3-8B",
]

# CSV key -> display name. The Odoo runs called
# @vertexai-hs3645/gemini-3.1-flash-lite-preview; the CSV key predates that.
MODEL_LABEL = {}  # csv key == display name; kept as a hook

PANELS = [
    ("odoo", "(a) Odoo — business domains"),
    ("appworld", "(b) AppWorld — apps"),
]

# A model x domain cell with fewer than this many HAR-defined trajectories is
# hatched and labelled with its n. Five is the threshold the sample forces: the
# Odoo cell median is 6, so a stricter threshold would hatch most of the panel and
# destroy the contrast that makes hatching mean anything, while a looser one would
# leave gpt-4o-mini's n=1 cells looking like its n=9 cells.
THIN_N = 5

# Colour clip. All but one cell falls at or below this; mapping to the true
# maximum (100.0, on 3 trajectories) would compress every other cell into the
# neutral band of the ramp to accommodate a single thin outlier.
VMAX = 60.0

# The declared reference level the scale diverges about. Fixed, not fitted: see
# the colour note in the module docstring. Round, adjacent to both pooled HARs
# without being either, and a 50/45 split of the drawn cells.
CENTER = 15.0

# Columns that are dropped rather than drawn, with the reason printed to stdout
# and stated in the figure footnote.
DROP_EMPTY_DOMAIN = ""          # AppWorld: 14 trajectories, 0 with a defined HAR
DROP_SPARSE = {"appworld": {"supervisor"}}   # 1 trajectory, 4 of 5 cells empty

# --------------------------------------------------------------------------- #
# Style
# --------------------------------------------------------------------------- #

SURFACE = "#FFFFFF"
TEXT = "#333333"
MUTED = "#777777"
RULE = "#B0B0B0"
EMPTY_FILL = "#F0F0F0"

# Diverging ramp, listed explicitly so the figure does not move if a matplotlib
# release re-tunes a built-in. Blue arm in the family of the paper's #1F5C99,
# red arm in the family of the warm #B3590A, near-white at the centre.
#
# Exactly nine anchors with the neutral FIFTH, so the neutral lands on colormap
# position 0.5 -- which is where TwoSlopeNorm sends CENTER. Any other count would
# put the white band somewhere other than the declared reference and the scale
# would quietly lie.
#
# Blue/red, requested over the blue/orange this figure used previously. Orange is
# the safer warm hue under dichromacy -- protan and deutan mute red far more than
# they mute orange -- so the red arm here is built to mirror the blue arm's
# LIGHTNESS step for step (L* ~86 / 71 / 55 / 38 on both sides). Direction is then
# recoverable from lightness alone, which is what carries the figure in grayscale
# and under protanopia; hue only has to carry the sign for normal vision.
RAMP_LOW = ["#1F5C99", "#5286B8", "#8FB2D2", "#C7DAE9"]   # vmin -> centre
NEUTRAL = "#F7F7F7"                                       # the declared reference
RAMP_HIGH = ["#F6D3CD", "#E8A294", "#D06A57", "#A82D1B"]  # centre -> vmax
RAMP = RAMP_LOW + [NEUTRAL] + RAMP_HIGH
assert len(RAMP) == 9 and RAMP[4] == NEUTRAL, "neutral must sit at colormap 0.5"
CMAP = LinearSegmentedColormap.from_list("har_div", RAMP, N=256)

# Unequal arms: 15 points of range below the reference, 45 above. Declared, not
# equalised -- equalising would compress the top of the range, i.e. the cells the
# figure exists to show.
NORM = TwoSlopeNorm(vmin=0.0, vcenter=CENTER, vmax=VMAX)

# Hatch for thin cells: works in colour, in grayscale, under every CVD type and
# in forced-colours print, i.e. it does not rest on the colour channel at all.
# Its colour follows the cell ink rather than being fixed -- a fixed dark hatch
# disappears into the deep end of the ramp, and the deep end is where the two
# thinnest, most extreme cells live (60.0 on n=1, 100.0 on n=3), i.e. exactly the
# cells the mark exists to qualify.
HATCH = "///"

# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _num(raw: str | None) -> float | None:
    """Parse a CSV cell to float, mapping blanks and NaN to None.

    float('nan') is not None and NaN != NaN, so an explicit math.isnan guard is
    required -- `if value` or `value is not None` lets NaN through and silently
    poisons the mean.
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


def _macro(rows, column="har_verdict"):
    """Macro mean over trajectories where `column` is defined, in percent.

    Returns (percent, n_defined). Exclusion is per-metric: a row dropped here for
    a blank har_verdict would still count toward a separate _macro on r_verdict.
    """
    values = [v for v in (_num(r[column]) for r in rows) if v is not None]
    if not values:
        return float("nan"), 0
    return 100.0 * sum(values) / len(values), len(values)


def load_rows(env: str):
    with CSV_PATHS[env].open(newline="") as fh:
        return list(csv.DictReader(fh))


def compute(env: str, rows):
    """-> dict with the drawn column list, the cell grid, and both marginals."""
    seen = sorted({r["domain"] for r in rows})

    dropped = []
    kept = []
    for d in seen:
        sub = [r for r in rows if r["domain"] == d]
        _, n_def = _macro(sub)
        if d == DROP_EMPTY_DOMAIN:
            dropped.append((repr(d), len(sub), n_def, "unlabelled domain"))
        elif n_def == 0:
            dropped.append((d, len(sub), n_def, "no trajectory with a defined HAR"))
        elif d in DROP_SPARSE.get(env, set()):
            dropped.append((d, len(sub), n_def, "effectively unpopulated"))
        else:
            kept.append(d)

    per_domain = {d: _macro([r for r in rows if r["domain"] == d]) for d in kept}
    per_model = {m: _macro([r for r in rows if r["model"] == m]) for m in MODELS}

    # Columns ordered by pooled HAR, descending, so the column marginal reads as
    # a left-to-right gradient and no extra marginal row is needed.
    columns = sorted(kept, key=lambda d: -per_domain[d][0])

    grid = {}
    for m in MODELS:
        for d in columns:
            sub = [r for r in rows if r["model"] == m and r["domain"] == d]
            har, n_def = _macro(sub)
            grid[(m, d)] = {"har": har, "n": n_def, "n_traj": len(sub)}

    return {
        "env": env,
        "columns": columns,
        "dropped": dropped,
        "grid": grid,
        "per_domain": per_domain,
        "per_model": per_model,
        "pooled": _macro(rows),
        "n_rows": len(rows),
    }


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

# The published marginals. If a data refresh moves one of these, this figure must
# not quietly disagree with the table it sits next to.
EXPECTED_MODEL = {
    "odoo": [3.3, 4.2, 16.1, 32.1, 45.9],
    "appworld": [7.3, 4.8, 18.2, 32.2, 18.0],
}
EXPECTED_ODOO_DOMAIN = {
    "inventory": 20.9, "project": 20.1, "sales": 18.9, "crm": 18.6,
    "helpdesk": 17.2, "purchase": 17.0, "manufacturing": 13.0,
    "accounting": 12.5, "hr": 10.9, "pos": 9.4,
}


def verify(stats: dict) -> None:
    env = stats["env"]
    for m, want in zip(MODELS, EXPECTED_MODEL[env]):
        got = round(stats["per_model"][m][0], 1)
        assert got == want, f"{env} {m}: got {got}, published {want}"
    if env == "odoo":
        for d, want in EXPECTED_ODOO_DOMAIN.items():
            got = round(stats["per_domain"][d][0], 1)
            assert got == want, f"odoo domain {d}: got {got}, published {want}"


def _relative_luminance(color) -> float:
    """WCAG relative luminance. Accepts an RGBA tuple or any matplotlib colour spec."""
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    """WCAG contrast ratio between two colours."""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


WHITE_INK = "#FFFFFF"


def _ink_for(face):
    """Pick the cell-label ink with the better contrast against this cell.

    A diverging ramp is dark at BOTH ends, so a fixed rule that assumes "pale
    background" fails on the blue arm exactly as it fails on the red one. Choosing
    per cell keeps every label on the better side of the crossover.
    """
    return WHITE_INK if _contrast(face, WHITE_INK) >= _contrast(face, TEXT) else TEXT


def check_label_contrast(panels) -> tuple[float, str]:
    """-> (worst contrast ratio over drawn cells, where it occurs).

    Reported rather than asserted: the crossover band of any diverging ramp sits
    near 3:1 for both candidate inks, which is the WCAG non-text floor and the
    right bar for a figure annotation. If this ever drops below 3.0 the ramp needs
    re-stepping, so the number is printed on every run instead of being trusted.
    """
    worst, where = 99.0, ""
    for stats, _ in panels:
        for m in MODELS:
            for d in stats["columns"]:
                cell = stats["grid"][(m, d)]
                if not cell["n"]:
                    continue
                face = CMAP(NORM(min(cell["har"], VMAX)))
                ratio = _contrast(face, _ink_for(face))
                if ratio < worst:
                    worst, where = ratio, f"{m} x {d} ({cell['har']:.1f}%)"
    return worst, where


# --------------------------------------------------------------------------- #
# Plot
# --------------------------------------------------------------------------- #

CELL_GAP = 0.018      # surface gap between fills, ~2px at 400 dpi


def draw_panel(ax, stats, title, ncol_max):
    columns = stats["columns"]
    ncols, nrows = len(columns), len(MODELS)

    # Cells keep the SAME physical size in both panels even though the panels
    # have different column counts, so the two grids are visually comparable; the
    # shorter panel simply ends earlier. (Axes widths are set by the caller to
    # match; xlim is padded to the wider panel's count so nothing rescales.)
    ax.set_xlim(0, ncol_max)
    ax.set_ylim(nrows, 0)
    ax.set_aspect("auto")

    for i, model in enumerate(MODELS):
        for j, dom in enumerate(columns):
            cell = stats["grid"][(model, dom)]
            har, n = cell["har"], cell["n"]
            x, y = j + CELL_GAP / 2, i + CELL_GAP / 2
            w = h = 1 - CELL_GAP

            if n == 0:
                ax.add_patch(Rectangle((x, y), w, h, facecolor=EMPTY_FILL,
                                       edgecolor="none", zorder=2))
                ax.text(j + 0.5, i + 0.5, "–", ha="center", va="center",
                        fontsize=5.4, color=MUTED, zorder=4)
                continue

            face = CMAP(NORM(min(har, VMAX)))
            thin = n < THIN_N
            ink = _ink_for(face)
            ax.add_patch(Rectangle((x, y), w, h, facecolor=face,
                                   edgecolor="none", zorder=2))
            if thin:
                # Hatch is drawn as the patch edge, so it needs its own zero-fill
                # overlay patch to sit on top of the colour without dulling it.
                ax.add_patch(Rectangle((x, y), w, h, facecolor="none",
                                       edgecolor=ink, hatch=HATCH,
                                       linewidth=0.0, zorder=3))

            if thin:
                # The value sits high and the count directly under it, so a thin
                # cell states its own support instead of deferring to the key.
                # A halo in the cell's own fill keeps the hatch from striking
                # through the digits -- without it the marked cells become the
                # least readable ones, which inverts the point of marking them.
                halo = [pe.withStroke(linewidth=1.9, foreground=face)]
                ax.text(j + 0.5, i + 0.345, f"{har:.1f}", ha="center", va="center",
                        fontsize=5.2, color=ink, zorder=5, path_effects=halo)
                ax.text(j + 0.5, i + 0.725, f"n={n}", ha="center", va="center",
                        fontsize=4.4, color=ink, zorder=5, path_effects=halo)
            else:
                ax.text(j + 0.5, i + 0.5, f"{har:.1f}", ha="center", va="center",
                        fontsize=5.4, color=ink, zorder=5)

    ax.set_xticks(np.arange(ncols) + 0.5)
    ax.set_xticklabels([c.replace("_", "-") for c in columns],
                       rotation=30, ha="right", rotation_mode="anchor",
                       fontsize=5.5, color=TEXT)
    ax.set_yticks(np.arange(nrows) + 0.5)
    ax.set_yticklabels([MODEL_LABEL.get(m, m) for m in MODELS], fontsize=5.8, color=TEXT)
    ax.tick_params(axis="both", length=0, pad=1.6)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.set_title(title, fontsize=6.8, color=TEXT, pad=3.0, loc="left")


def build(panels):
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
            "hatch.linewidth": 0.35,
        }
    )

    ncol_max = max(len(s["columns"]) for s, _ in panels)

    # Explicit rectangles, and savefig without bbox_inches="tight", so the emitted
    # canvas is exactly FIG_W x FIG_H -- one text column, no rescaling in LaTeX.
    fig = plt.figure(figsize=(FIG_W, FIG_H))

    # These are FIGURE FRACTIONS, so they have to be restated whenever FIG_H
    # changes or the layout silently rescales.  Dropping the four-line footnote
    # took the canvas from 3.34in to 2.96in; the values below hold the ABSOLUTE
    # geometry that was tuned for the taller canvas -- 0.188in per row, 0.43in
    # between the panels for panel (a)'s rotated labels plus panel (b)'s title,
    # and 0.36in under panel (b) for its rotated labels and nothing else.
    left, cell_w = 0.150, 0.0715
    row_h = 0.0635                      # 0.188 in x 5 rows = 0.94 in
    y_a, y_b = 0.586, 0.122

    axes = []
    for (stats, title), y0 in zip(panels, (y_a, y_b)):
        width = cell_w * len(stats["columns"])
        ax = fig.add_axes([left, y0, width, row_h * len(MODELS)])
        draw_panel(ax, stats, title, ncol_max=len(stats["columns"]))
        axes.append(ax)

    # One colourbar for both panels, spanning both, because one scale shared by
    # two panels is the only way a colour means the same thing in each.
    cb_x = left + cell_w * ncol_max + 0.028
    cax = fig.add_axes([cb_x, y_b, 0.019, (y_a + row_h * len(MODELS)) - y_b])
    # Linear in VALUE, not in colormap position: the reference then sits a quarter
    # of the way up and the reader SEES that the arms are unequal (15 below, 45
    # above) instead of having to take the footnote's word for it.
    values = np.linspace(VMAX, 0.0, 512)
    cax.imshow(NORM(values).reshape(-1, 1), cmap=CMAP, aspect="auto",
               extent=(0, 1, 0, VMAX), vmin=0, vmax=1)
    cax.set_xticks([])
    cax.set_yticks([0, CENTER, 30, 45, 60])
    cax.set_yticklabels(["0", f"{CENTER:.0f}  ref.", "30", "45", "≥60"],
                        fontsize=5.2, color=TEXT)
    # The reference is a declared level, so it gets a rule across the bar rather
    # than just a tick: it is the one value on this scale that means something.
    cax.plot([0, 1], [CENTER, CENTER], color=TEXT, linewidth=0.55, zorder=4)
    cax.yaxis.tick_right()
    cax.tick_params(axis="y", length=1.6, width=0.4, color=RULE, pad=1.4)
    for side in ("top", "right", "left", "bottom"):
        cax.spines[side].set_visible(False)
    cax.set_ylabel("HAR (%)", fontsize=6.0, color=TEXT, labelpad=2.0)
    cax.yaxis.set_label_position("right")

    # [REMOVED] The four-line in-figure footnote. It printed at 4.6pt -- below
    # any print legibility floor -- and said the same things as the LaTeX caption
    # in figures/../iclr2026_conference.tex (app:breakdowns), so the reader met
    # the reference line, the unequal arms and the hatching rule twice, once
    # illegibly. All of it now lives in the caption at body size. The facts the
    # caption must carry, since nothing else states them: macro averaging with
    # per-metric exclusion, columns ordered by pooled HAR, the clipped
    # qwen3-8B x inventory cell, and AppWorld's two dropped columns.
    return fig


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def print_grid(stats) -> None:
    env, columns = stats["env"], stats["columns"]
    print(f"\n-- {env}: HAR % (n with a defined HAR) by model x domain --")
    width = 13
    print(f"{'model':19s}" + "".join(f"{c[:11]:>{width}s}" for c in columns) + f"{'MODEL':>{width}s}")
    for m in MODELS:
        cells = []
        for d in columns:
            c = stats["grid"][(m, d)]
            mark = "*" if 0 < c["n"] < THIN_N else " "
            cells.append(f"{c['har']:6.1f}(n={c['n']:2d}){mark}" if c["n"]
                         else f"{'--':>6s}(n= 0) ")
        mh, mn = stats["per_model"][m]
        print(f"{m:19s}" + "".join(f"{c:>{width}s}" for c in cells)
              + f"{mh:7.1f}(n={mn:3d})")
    margins = []
    for d in columns:
        dh, dn = stats["per_domain"][d]
        margins.append(f"{dh:6.1f}(n={dn:2d}) ")
    ph, pn = stats["pooled"]
    print(f"{'DOMAIN':19s}" + "".join(f"{c:>{width}s}" for c in margins)
          + f"{ph:7.1f}(n={pn:3d})")

    ns = [stats["grid"][(m, d)]["n"] for m in MODELS for d in columns]
    thin = sum(1 for n in ns if 0 < n < THIN_N)
    print(f"  cells={len(ns)}  median n={int(np.median(ns))}  min={min(ns)}  max={max(ns)}"
          f"  hatched (n<{THIN_N})={thin}   (* = hatched in the figure)")
    for name, n_traj, n_def, why in stats["dropped"]:
        print(f"  DROPPED column {name}: {n_traj} trajectories, {n_def} with a defined HAR"
              f" -- {why}")


def main() -> None:
    panels = []
    for env, title in PANELS:
        rows = load_rows(env)
        stats = compute(env, rows)
        verify(stats)
        panels.append((stats, title))
        print(f"source: {CSV_PATHS[env]}  ({stats['n_rows']} trajectories)")

    print("\nmarginals verified against the published values "
          "(per-model both envs, per-domain Odoo).")

    for stats, _ in panels:
        print_grid(stats)

    worst, where = check_label_contrast(panels)
    print(f"\ndiverging scale: blue {RAMP_LOW[0]} -> {NEUTRAL} at the declared "
          f"reference {CENTER:.0f}% -> red {RAMP_HIGH[-1]}, clipped at {VMAX:.0f}%.")
    print(f"  arms are unequal by design: 0-{CENTER:.0f} below, {CENTER:.0f}-{VMAX:.0f} above.")
    print(f"  worst cell-label contrast {worst:.2f}:1 at {where} "
          f"(WCAG non-text floor is 3.0:1).")
    print("  grayscale ordering is NOT preserved by a diverging ramp -- accepted; "
          "every cell prints its value.")

    pooled = [stats["pooled"] for stats, _ in panels]
    print(f"pooled HAR: odoo {pooled[0][0]:.2f} (n={pooled[0][1]}), "
          f"appworld {pooled[1][0]:.2f} (n={pooled[1][1]})")

    fig = build(panels)
    targets = [OUT_DIR / "har_model_by_domain.png", OUT_DIR / "har_model_by_domain.pdf"]
    if LATEX_FIG_DIR.is_dir():
        # Both: \includegraphics picks the PDF, the PNG is for quick viewing.
        targets += [LATEX_FIG_DIR / "har_model_by_domain.png",
                    LATEX_FIG_DIR / "har_model_by_domain.pdf"]

    print()
    for path in targets:
        # No bbox_inches="tight": the canvas must stay exactly FIG_W x FIG_H.
        kwargs = {"dpi": 400} if path.suffix == ".png" else {}
        fig.savefig(path, **kwargs)
        print(f"wrote {path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
