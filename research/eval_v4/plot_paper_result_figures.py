#!/usr/bin/env python3
"""Generate publication-ready visualizations for RQ1--RQ3."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch


OUT = Path(__file__).resolve().parent / "paper_figures"
OUT.mkdir(exist_ok=True)

BLUE = "#557D9F"
BLUE_LIGHT = "#C8D9E6"
RED = "#BD6754"
RED_LIGHT = "#E9C5B7"
GOLD = "#C99A45"
PURPLE = "#8073AC"
GRAY = "#8B9299"
LIGHT_GRAY = "#D9DDE1"
TEXT = "#30343B"
GRID = "#E8EAED"

MODELS = ["DeepSeek-Chat", "DeepSeek-Reasoner", "Gemini-3.1-Flash", "GPT-4o-mini", "Qwen3-8B"]


def setup_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "font.size": 9,
            "axes.labelcolor": TEXT,
            "text.color": TEXT,
            "xtick.color": TEXT,
            "ytick.color": TEXT,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save(fig: plt.Figure, stem: str) -> None:
    for ext in ("pdf", "png"):
        kwargs = {"bbox_inches": "tight", "pad_inches": 0.04}
        if ext == "png":
            kwargs["dpi"] = 400
        path = OUT / f"{stem}.{ext}"
        fig.savefig(path, **kwargs)
        print(path)
    plt.close(fig)


def clean_axis(ax: plt.Axes) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#A8ADB3")
    ax.spines["bottom"].set_linewidth(0.7)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", color="#A8ADB3", labelsize=8)


def plot_spread() -> None:
    """Compare observed marginal variation on one common HAR scale."""
    groups = [
        ("Model", np.array([4.7, 5.6, 28.1, 29.8, 38.6]), BLUE),
        ("Domain", np.array([9.2, 10.0, 12.0, 12.2, 13.8, 14.0, 15.3, 17.3, 18.2, 20.6]), GRAY),
        ("Difficulty", np.array([11.6, 12.1, 14.4, 16.0]), GRAY),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 2.55))
    fig.subplots_adjust(left=0.17, right=0.96, top=0.86, bottom=0.25)

    y = np.arange(3)
    for yi, (name, values, color) in zip(y, groups):
        ax.plot([values.min(), values.max()], [yi, yi], color=color, lw=5.5, solid_capstyle="round", zorder=1)
        ax.scatter(values, np.full_like(values, yi), s=31 if name == "Model" else 25,
                   color=color, edgecolor="white", linewidth=0.7, zorder=2)
        ax.text(values.min() - 0.75, yi, f"{values.min():.1f}", ha="right", va="center", fontsize=8, color=color)
        ax.text(values.max() + 0.75, yi, f"{values.max():.1f}", ha="left", va="center", fontsize=8, color=color)
        spread = values.max() - values.min()
        ax.text(43.2, yi, f"{spread:.1f} pp", ha="left", va="center", fontsize=8,
                color=color, fontweight="bold" if name == "Model" else "normal")

    ax.set_yticks(y)
    ax.set_yticklabels([g[0] for g in groups], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 50)
    ax.set_xticks(np.arange(0, 41, 10))
    ax.set_xlabel("HAR (%)", labelpad=7)
    ax.xaxis.grid(True, color=GRID, lw=0.65, zorder=0)
    clean_axis(ax)
    ax.text(0.0, 1.08, "Observed variation across evaluation slices", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=10.5, fontweight="bold")
    ax.text(1.0, 1.08, "range", transform=ax.transAxes, ha="right", va="bottom",
            fontsize=8, color=GRAY)
    save(fig, "rq1_model_domain_difficulty_spread")


def plot_fact_vs_har() -> None:
    fact = np.array([2.4, 1.3, 1.3, 3.9, 3.0])
    har = np.array([4.7, 5.6, 28.1, 29.8, 38.6])
    har_sev = np.array([0.2, 0.4, 0.0, 5.1, 6.6])
    colors = [BLUE, BLUE, PURPLE, RED, RED]

    fig, ax = plt.subplots(figsize=(4.8, 3.5))
    fig.subplots_adjust(left=0.16, right=0.95, top=0.87, bottom=0.18)
    sizes = 52 + har_sev * 22
    ax.scatter(fact, har, s=sizes, c=colors, alpha=0.94, edgecolor="white", linewidth=0.9, zorder=3)

    offsets = [(7, -2), (7, 7), (7, 5), (7, -10), (7, 4)]
    for x, y, name, off in zip(fact, har, MODELS, offsets):
        ax.annotate(name, (x, y), xytext=off, textcoords="offset points", fontsize=7.5,
                    ha="left", va="center")

    ax.axhspan(20, 42, color=RED_LIGHT, alpha=0.13, zorder=0)
    ax.text(0.03, 0.97, "Low factual fabrication,\nbut high action mismatch",
            transform=ax.transAxes, ha="left", va="top", fontsize=8, color=RED)
    ax.set_xlim(0.8, 4.8)
    ax.set_ylim(0, 42)
    ax.set_xticks([1, 2, 3, 4])
    ax.set_yticks([0, 10, 20, 30, 40])
    ax.set_xlabel("Fact-fabrication rate (%)", labelpad=7)
    ax.set_ylabel("HAR (%)", labelpad=7)
    ax.grid(True, color=GRID, lw=0.65, zorder=0)
    clean_axis(ax)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color("#A8ADB3")
    ax.spines["left"].set_linewidth(0.7)
    ax.text(0.0, 1.04, "Factuality does not reveal action mismatch", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=10.5, fontweight="bold")
    ax.text(0.98, 0.03, "Bubble size = HAR$_{sev}$", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=7, color=GRAY)
    save(fig, "rq2_fact_fabrication_vs_har")


def plot_failure_composition() -> None:
    # One extraction artifact is excluded. Columns are mutually exclusive gates.
    counts = np.array(
        [
            [47, 21, 0, 23, 0],   # DeepSeek-Chat
            [26, 4, 1, 52, 8],    # DeepSeek-Reasoner
            [1, 0, 0, 231, 0],    # Gemini-Flash
            [0, 3, 4, 127, 2],    # GPT-4o-mini
            [12, 5, 3, 153, 12],  # Qwen3-8B
        ],
        dtype=float,
    )
    labels = ["C1 Unexecuted", "C2 Misgrounded", "C3 Unverified", "C4 Undisclosed read", "C4 Hidden mutation"]
    colors = [BLUE_LIGHT, GOLD, PURPLE, LIGHT_GRAY, RED]
    totals = counts.sum(axis=1)
    pct = counts / totals[:, None] * 100

    fig, ax = plt.subplots(figsize=(7.2, 3.25))
    fig.subplots_adjust(left=0.235, right=0.97, top=0.74, bottom=0.2)
    y = np.arange(len(MODELS))
    left = np.zeros(len(MODELS))
    for j, (label, color) in enumerate(zip(labels, colors)):
        ax.barh(y, pct[:, j], left=left, height=0.56, color=color, edgecolor="white",
                linewidth=0.5, label=label)
        for i, value in enumerate(pct[:, j]):
            if value >= 8:
                text_color = "white" if color in (PURPLE, RED) else TEXT
                ax.text(left[i] + value / 2, i, f"{int(counts[i, j])}", ha="center", va="center",
                        fontsize=7.5, color=text_color)
        left += pct[:, j]

    ax.set_yticks(y)
    ax.set_yticklabels([f"{m}  ($n$={int(n)})" for m, n in zip(MODELS, totals)], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks(np.arange(0, 101, 20))
    ax.set_xticklabels([f"{x}%" for x in np.arange(0, 101, 20)])
    ax.set_xlabel("Composition of genuine halluci-action instances within each model", labelpad=7)
    ax.xaxis.grid(True, color=GRID, lw=0.55, zorder=0)
    clean_axis(ax)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.04), ncol=3, frameon=False,
              fontsize=7.2, columnspacing=1.1, handlelength=1.4, handletextpad=0.45)
    ax.text(0.0, 1.27, "Models exhibit distinct failure signatures", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=10.5, fontweight="bold")
    save(fig, "rq3_failure_composition_by_model")


def _box(ax: plt.Axes, x: float, y: float, w: float, h: float, title: str, subtitle: str,
         face: str, edge: str, title_size: float = 8.2, subtitle_size: float = 6.7) -> None:
    patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.018,rounding_size=0.025",
                           facecolor=face, edgecolor=edge, linewidth=1.0)
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h * 0.63, title, ha="center", va="center",
            fontsize=title_size, fontweight="bold")
    ax.text(x + w / 2, y + h * 0.29, subtitle, ha="center", va="center",
            fontsize=subtitle_size, color="#555B62")


def plot_fault_tree() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.02, 0.98, "Where does the say–do alignment chain break?", fontsize=10.5,
            fontweight="bold", ha="left", va="top")

    # Claim-anchored sequential gates.
    xs = [0.02, 0.265, 0.51]
    titles = ["C1  Execution", "C2  Grounding", "C3  Verification"]
    questions = ["Was the operation executed?", "Correct target and parameters?", "Was the claimed result achieved?"]
    failures = ["Unexecuted commitment\n$n=86$", "Misgrounded execution\n$n=33$", "Unverified outcome\n$n=8$"]
    colors = [BLUE_LIGHT, "#EBD9B4", "#D9D2E9"]
    edges = [BLUE, GOLD, PURPLE]

    for x, title, q, fail, face, edge in zip(xs, titles, questions, failures, colors, edges):
        _box(ax, x, 0.56, 0.19, 0.21, title, q, "#F8F9FA", edge,
             title_size=8.0, subtitle_size=6.2)
        _box(ax, x, 0.15, 0.19, 0.19, fail.split("\n")[0], fail.split("\n")[1], face, edge,
             title_size=7.2, subtitle_size=7.0)
        ax.add_patch(FancyArrowPatch((x + 0.095, 0.56), (x + 0.095, 0.36), arrowstyle="-|>",
                                     mutation_scale=9, linewidth=0.9, color=edge))
        ax.text(x + 0.108, 0.455, "no", fontsize=7, color=edge, va="center")

    for x1, x2 in zip(xs[:-1], xs[1:]):
        ax.add_patch(FancyArrowPatch((x1 + 0.192, 0.68), (x2 - 0.005, 0.68), arrowstyle="-|>",
                                     mutation_scale=9, linewidth=0.9, color=GRAY))

    # Action-anchored disclosure gate is parallel, not a fourth sequential claim gate.
    ax.plot([0.735, 0.735], [0.11, 0.83], color=GRID, lw=1.0)
    _box(ax, 0.78, 0.56, 0.20, 0.21, "C4  Disclosure", "Was every action disclosed?",
         "#F8F9FA", RED, title_size=8.0, subtitle_size=6.2)
    _box(ax, 0.78, 0.15, 0.20, 0.19, "Undisclosed execution", "$n=608$", RED_LIGHT, RED,
         title_size=7.2, subtitle_size=7.0)
    ax.add_patch(FancyArrowPatch((0.88, 0.56), (0.88, 0.36), arrowstyle="-|>", mutation_scale=9,
                                 linewidth=0.9, color=RED))
    ax.text(0.893, 0.455, "no", fontsize=7, color=RED, va="center")
    ax.text(0.88, 0.82, "action-anchored", fontsize=7.0, color=GRAY, ha="center")
    ax.text(0.385, 0.82, "claim-anchored", fontsize=7.0, color=GRAY, ha="center")
    ax.text(0.5, 0.035, "One extraction artifact excluded; 735 genuine instances map to exactly one failure gate.",
            ha="center", va="bottom", fontsize=7, color=GRAY)
    save(fig, "rq3_c1_c4_fault_tree")


def main() -> None:
    setup_style()
    plot_spread()
    plot_fact_vs_har()
    plot_failure_composition()
    plot_fault_tree()


if __name__ == "__main__":
    main()
