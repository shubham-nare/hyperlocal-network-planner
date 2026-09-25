"""Chart for reports/revealed_demand.md: recall by method, strictest protocol (brand + city hidden)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
HIGHLIGHT, NEUTRAL = "#2a78d6", "#a8a7a1"
METHODS = {  # summary method -> (label, highlighted)
    "random": ("Random placement", False),
    "lightgbm_top_k": ("LightGBM, hex-by-hex (Phase 1 style)", False),
    "demand_index_max_coverage": ("v1 demand index + max coverage", False),
    "competitor_max_coverage": ("Copy competitors + max coverage", False),
    "catchment+spacing_greedy": ("Learned demand + spacing (no competitor data)", True),
    "structural_greedy": ("Full structural model", True),
    "spacing+competition_no_features_greedy": ("Spacing + competitors, no demand features", True),
}


def main() -> None:
    s = pd.read_csv("reports/revealed_demand_summary.csv")
    s = s[s["protocol"] == "leave_brand_and_city_out"].set_index("method").loc[list(METHODS)]
    folds = pd.read_csv("reports/revealed_demand_folds.csv")
    n_hexes = int(folds[(folds["protocol"] == "leave_brand_and_city_out") & (folds["method"] == "random")]["k"].sum())
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True, facecolor=SURFACE)
    for ax, (col, title) in zip(axes, [("recall_0.5km", "Same hex (within 0.5 km)"),
                                        ("recall_1.5km", "Within 1.5 km (v1 holdout metric)")]):
        vals = s[col].to_numpy()
        colors = [HIGHLIGHT if METHODS[m][1] else NEUTRAL for m in s.index]
        y = range(len(vals))
        ax.barh(y, vals, height=0.62, color=colors, edgecolor=SURFACE, linewidth=2)
        for yi, v in zip(y, vals):
            ax.text(v + 0.008, yi, f"{v:.0%}", va="center", ha="left", fontsize=9, color=INK)
        ax.set_facecolor(SURFACE)
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.set_xlim(0, max(vals) * 1.18)
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=INK_2, labelsize=9, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0].set_yticks(range(len(METHODS)), [METHODS[m][0] for m in s.index])
    fig.suptitle("Share of real dark-store hexes re-found when the brand AND the city were hidden from fitting\n"
                 f"9 held-out networks (3 brands × 3 cities), pooled over {n_hexes} real store hexes", x=0.01, ha="left",
                 fontsize=11.5, color=INK)
    fig.text(0.01, -0.02, "Blue = spacing-aware models from this module; gray = baselines. Features: Overture Maps + Meta HRSL "
             "(not v1's WorldPop/OSM). Stores: darkstores snapshot, Mar 2026.", fontsize=8.5, color=INK_2)
    fig.tight_layout()
    fig.savefig("reports/revealed_demand_recall.png", dpi=150, bbox_inches="tight", facecolor=SURFACE)


if __name__ == "__main__":
    main()
