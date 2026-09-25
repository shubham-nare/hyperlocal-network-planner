"""Chart for reports/competition.md: the leader's 3-year gain from each plan, by how competitors respond."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
PLANS = {  # categorical slots 1-3 of the reference palette, fixed order
    "naive": ("Naive: plan as if rivals stand still", "#2a78d6"),
    "aware_rational": ("Anticipates rational rivals", "#eb6834"),
    "aware_behavioural": ("Anticipates rivals' revealed behaviour", "#1baf7a"),
}
RESPONSES = {"frozen": "Rivals don't expand", "rational": "Rivals respond\nrationally", "behavioural": "Rivals respond as\ntheir history suggests"}


def main() -> None:
    s = pd.read_csv("reports/competition_summary.csv")
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.3), sharey=True, facecolor=SURFACE)
    width = 0.26
    for ax, city in zip(axes, ("hyderabad", "bengaluru", "pune")):
        c = s[s["city"] == city]
        for k, (plan, (label, colour)) in enumerate(PLANS.items()):
            vals = [float(c[(c["plan"] == plan) & (c["follower_model"] == r)]["leader_incremental_value_cr"].iloc[0])
                    for r in RESPONSES]
            x = np.arange(len(RESPONSES)) + (k - 1) * width
            ax.bar(x, vals, width=width - 0.03, color=colour, label=label, edgecolor=SURFACE, linewidth=2)
            for xi, v in zip(x, vals):
                ax.text(xi, v + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=7.5, color=INK_2)
        ax.set_xticks(range(len(RESPONSES)), list(RESPONSES.values()))
        ax.set_title(city.title(), loc="left", fontsize=11, color=INK)
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=INK_2, labelsize=8.5, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0].set_ylabel("Blinkit's 3-year margin gain vs doing nothing (INR Cr)", color=INK_2, fontsize=9)
    axes[0].legend(loc="upper left", fontsize=8.5, frameon=False, labelcolor=INK)
    axes[0].set_ylim(0, axes[0].get_ylim()[1] * 1.25)
    fig.suptitle("10 new Blinkit stores; Zepto and Instamart then add 10 each. Gain is measured against Blinkit adding "
                 "nothing while rivals still expand", x=0.01, ha="left", fontsize=11.5, color=INK)
    fig.text(0.01, -0.03, "Margin on incremental orders over 3 years, before the 10 stores' fixed costs and capex (the same for "
             "every plan). Modelled: Huff shares across brands (an assumption), capacity 2,094/day,\nv1-calibrated demand, "
             "margin from the Week-3 scenarios. Not a forecast.", fontsize=8.5, color=INK_2)
    fig.tight_layout()
    fig.savefig("reports/competition_value.png", dpi=150, bbox_inches="tight", facecolor=SURFACE)


if __name__ == "__main__":
    main()
