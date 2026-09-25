"""Chart for reports/rollout_plan.md: 3-year value gained over v1's plan, by policy and demand uncertainty."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
POLICIES = {  # policy -> (label, colour): categorical slots 1-3 of the reference palette, fixed order
    "robust_all_now": ("Robust plan, open all now", "#2a78d6"),
    "staged_no_learning": ("Staged, no learning (cost of waiting)", "#eb6834"),
    "staged_robust_learning": ("Staged + learning", "#1baf7a"),
}
CITIES = ("hyderabad", "bengaluru", "pune")


def main() -> None:
    s = pd.read_csv("reports/rollout_simulation_summary.csv")
    s = s[s["scenario"].str.startswith("sigma=")]
    sigmas = sorted(s["sigma"].unique())
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), sharey=True, facecolor=SURFACE)
    width = 0.24
    for ax, city in zip(axes, CITIES):
        c = s[s["city"] == city]
        for k, (policy, (label, colour)) in enumerate(POLICIES.items()):
            rows = c[c["policy"] == policy].set_index("sigma").loc[sigmas]
            x = np.arange(len(sigmas)) + (k - 1) * width
            err = np.vstack([rows["gain_vs_v1_cr"] - rows["gain_ci_low_cr"], rows["gain_ci_high_cr"] - rows["gain_vs_v1_cr"]])
            ax.bar(x, rows["gain_vs_v1_cr"], width=width - 0.03, color=colour, label=label, edgecolor=SURFACE, linewidth=2)
            ax.errorbar(x, rows["gain_vs_v1_cr"], yerr=err, fmt="none", ecolor=INK_2, elinewidth=1, capsize=2)
        ax.axhline(0, color=INK_2, linewidth=1)
        ax.set_xticks(range(len(sigmas)), [f"×/÷ {np.exp(v):.1f}\n(σ={v})" for v in sigmas])
        ax.set_title(city.title(), loc="left", fontsize=11, color=INK)
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=INK_2, labelsize=9, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0].set_ylabel("3-year value vs v1's plan (INR crore)", color=INK_2, fontsize=9)
    axes[1].set_xlabel("Local demand-map error (1 s.d., multiplicative)", color=INK_2, fontsize=9)
    axes[0].legend(loc="upper left", fontsize=8.5, frameon=False, labelcolor=INK)
    n_worlds = int(pd.read_csv("reports/rollout_simulation_worlds.csv")["world"].nunique())
    fig.suptitle("What staging the rollout is worth, over opening v1's point-estimate plan all at once\n"
                 f"Blinkit, up to 40 new stores per city, 3 years; mean over {n_worlds} simulated demand worlds, "
                 "bars = 90% interval", x=0.01, ha="left", fontsize=11.5, color=INK)
    fig.text(0.01, -0.03, "Simulated: 'true' demand is drawn from a stated error model around v1's calibrated estimate "
             "(mean-preserving). Economics: the 81 Week-3 scenarios. Not a forecast.", fontsize=8.5, color=INK_2)
    fig.tight_layout()
    fig.savefig("reports/rollout_value_of_staging.png", dpi=150, bbox_inches="tight", facecolor=SURFACE)


if __name__ == "__main__":
    main()
