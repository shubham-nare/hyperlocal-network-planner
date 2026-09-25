"""Charts for reports/peak_sla.md: on-time share by hour per staffing policy; rider-hours per order vs store size."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE, INK, INK_2, GRID, BAND = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#f1f0ec"
POLICY = {  # categorical slots 1-3 of the reference palette, fixed order
    "util80": ("80% utilisation, hour by hour", "#2a78d6"),
    "same_budget": ("Same rider-hours, spread by the queue model", "#eb6834"),
    "erlang95": ("Queue model, 95% target", "#1baf7a"),
}
CITY = {"hyderabad": "#2a78d6", "bengaluru": "#eb6834", "pune": "#1baf7a"}


def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def hourly() -> None:
    h = pd.read_csv("reports/peak_sla_hourly.csv")
    h = h[h["evening_share"] == 0.35]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.0), sharey=True, facecolor=SURFACE)
    for ax, city in zip(axes, ("hyderabad", "bengaluru", "pune")):
        ax.axvspan(18.5, 21.5, color=BAND, zorder=0)
        ax.text(20, 0.505, "7–10 pm", ha="center", va="bottom", fontsize=8, color=INK_2)
        for policy, (label, colour) in POLICY.items():
            f = h[(h["city"] == city) & (h["policy"] == policy)].sort_values("hour")
            ax.plot(f["hour"], f["on_time"], color=colour, linewidth=2, label=label, marker="o", markersize=3)
        ax.set_title(city.title(), loc="left", fontsize=11, color=INK)
        ax.set_xticks([0, 6, 12, 18, 23], ["0:00", "6:00", "12:00", "18:00", "23:00"])
        ax.set_ylim(0.5, 1.0)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        _style(ax)
    axes[0].set_ylabel("Orders delivered within 10 min", color=INK_2, fontsize=9)
    axes[0].legend(loc="lower right", fontsize=8.5, frameon=False, labelcolor=INK)
    fig.suptitle("The 10-minute promise slips off-peak, not at peak, under the usual 80%-utilisation rule\n"
                 "Blinkit's existing stores, calibrated loads; share of each hour's orders arriving within the promise",
                 x=0.01, ha="left", fontsize=11.5, color=INK)
    fig.text(0.01, -0.03, "Model: M/G/c rider queue per store and hour; hourly demand shape, 2-min handover and trip "
             "variability are assumptions (7–10 pm = 35% of orders). Not observed data.", fontsize=8.5, color=INK_2)
    fig.tight_layout()
    fig.savefig("reports/peak_sla_by_hour.png", dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def pooling() -> None:
    po = pd.read_csv("reports/peak_sla_pooling.csv")
    fig, ax = plt.subplots(figsize=(7.5, 4.4), facecolor=SURFACE)
    for city, colour in CITY.items():
        f = po[po["city"] == city]
        ax.scatter(f["orders_per_day"], f["rider_hours_per_order"], s=26, color=colour, edgecolor=SURFACE,
                   linewidth=1.2, label=city.title(), alpha=0.9)
    floor = po["offered_rider_hours_per_order"].median()
    ax.axhline(floor, color=INK_2, linewidth=1, linestyle="--")
    ax.text(po["orders_per_day"].max(), floor * 1.06, "time riders are actually busy per order (median)",
            ha="right", va="bottom", fontsize=8, color=INK_2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Store orders/day (log)", color=INK_2, fontsize=9)
    ax.set_ylabel("Rider-hours per order for 95% on-time (log)", color=INK_2, fontsize=9)
    ax.set_yticks([0.15, 0.2, 0.3, 0.5, 1.0, 1.5], ["0.15", "0.2", "0.3", "0.5", "1", "1.5"])
    ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.legend(loc="upper right", fontsize=8.5, frameon=False, labelcolor=INK)
    ax.set_title("Small stores pay for idle riders: the same promise costs far more riders per order",
                 loc="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig("reports/peak_sla_pooling.png", dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    hourly()
    pooling()
    print("ok")
