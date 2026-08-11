#!/usr/bin/env python3
"""Create the camera-ready RQ1 diverging bar chart."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch


OUT_DIR = Path(__file__).resolve().parent

MODELS = [
    "DeepSeek-Chat",
    "DeepSeek-Reasoner",
    "Gemini-3.1-Flash",
    "GPT-4o-mini",
    "Qwen3-8B",
]

# Directional gaps and their severe subsets (percentage points).
SAID_NOT_DONE = np.array([6.7, 3.7, 0.9, 9.5, 21.3])
REQUIRED_MISS = np.array([0.4, 0.2, 0.0, 9.5, 9.6])
DONE_NOT_SAID = np.array([2.6, 7.5, 43.6, 42.7, 49.7])
FORBIDDEN_SILENT = np.array([0.0, 0.6, 0.0, 0.3, 3.3])

CLAIM_PALE = "#C8D9E6"
CLAIM_CORE = "#557D9F"
ACTION_PALE = "#E9C5B7"
ACTION_CORE = "#BD6754"
TEXT = "#333333"
GRID = "#E8E8E8"


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "font.size": 9,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    y = np.arange(len(MODELS))
    fig, ax = plt.subplots(figsize=(7.2, 3.55), constrained_layout=False)
    fig.subplots_adjust(left=0.245, right=0.975, top=0.79, bottom=0.22)

    bar_h = 0.48
    # Pale totals first; dark severe subsets are nested against the zero line.
    ax.barh(y, -SAID_NOT_DONE, height=bar_h, color=CLAIM_PALE, edgecolor="none", zorder=2)
    ax.barh(y, DONE_NOT_SAID, height=bar_h, color=ACTION_PALE, edgecolor="none", zorder=2)
    ax.barh(y, -REQUIRED_MISS, height=bar_h, color=CLAIM_CORE, edgecolor="none", zorder=3)
    ax.barh(y, FORBIDDEN_SILENT, height=bar_h, color=ACTION_CORE, edgecolor="none", zorder=3)

    ax.axvline(0, color="#777777", linewidth=0.8, zorder=4)
    ax.set_xlim(-55, 55)
    ax.set_ylim(-0.6, len(MODELS) - 0.4)
    ax.invert_yaxis()

    ticks = np.arange(-50, 51, 10)
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(abs(t)) for t in ticks])
    ax.set_yticks(y)
    ax.set_yticklabels(MODELS, fontsize=9)
    ax.tick_params(axis="y", length=0, pad=9)
    ax.tick_params(axis="x", length=3, color="#999999", labelsize=8)
    ax.xaxis.grid(True, color=GRID, linewidth=0.55, zorder=0)
    ax.yaxis.grid(False)

    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#AAAAAA")
    ax.spines["bottom"].set_linewidth(0.6)

    # Endpoint labels, kept inside the canvas even for the 49.7% bar.
    for yi, left, right in zip(y, SAID_NOT_DONE, DONE_NOT_SAID):
        ax.text(-left - 1.0, yi, f"{left:.1f}", ha="right", va="center", color=TEXT, fontsize=8)
        ax.text(right + 1.0, yi, f"{right:.1f}", ha="left", va="center", color=TEXT, fontsize=8)

    # Direction labels live above the axes, away from data and value labels.
    ax.text(
        0.25, 1.16, "\u2190  Said-not-done", transform=ax.transAxes,
        ha="center", va="center", color=CLAIM_CORE, fontsize=11, fontweight="bold"
    )
    ax.text(
        0.75, 1.16, "Done-not-said  \u2192", transform=ax.transAxes,
        ha="center", va="center", color=ACTION_CORE, fontsize=11, fontweight="bold"
    )

    legend = [
        Patch(facecolor="#D8D8D8", edgecolor="none", label="Directional gap"),
        Patch(facecolor="#777777", edgecolor="none", label="Severe subset"),
    ]
    ax.legend(
        handles=legend, loc="upper center", bbox_to_anchor=(0.5, 1.075),
        ncol=2, frameon=False, fontsize=7.5, handlelength=1.4,
        columnspacing=1.6, handletextpad=0.5
    )

    ax.set_xlabel(
        "% of verbal claims (left)     /     % of executed actions (right)",
        fontsize=8.5, labelpad=8
    )

    for suffix in ("pdf", "png"):
        path = OUT_DIR / f"rq1_har_by_model_matplotlib.{suffix}"
        kwargs = {"bbox_inches": "tight", "pad_inches": 0.03}
        if suffix == "png":
            kwargs["dpi"] = 400
        fig.savefig(path, **kwargs)
        print(path)

    plt.close(fig)


if __name__ == "__main__":
    main()
