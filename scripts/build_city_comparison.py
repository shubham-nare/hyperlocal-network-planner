"""Build a three-city expansion comparison from the saved network outputs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from build_memo import SCENARIOS, ROBUST_KM, md_table, robust_areas


CITIES = ("hyderabad", "bengaluru", "pune")


def required_csv(path: Path) -> pd.DataFrame:
    """Read a required report with an actionable error if a scenario is absent."""
    if not path.exists():
        raise FileNotFoundError(f"Missing required report: {path}")
    return pd.read_csv(path)


def city_summary(city: str) -> dict[str, object]:
    """Return comparison metrics using the same core-pick rule as the city memos."""
    curve = required_csv(Path(f"reports/network_{city}_base_curve.csv")).set_index("max_new_sites")
    for sites in (0, 10):
        if sites not in curve.index:
            raise ValueError(f"reports/network_{city}_base_curve.csv has no N={sites} row")

    served_today = float(curve.loc[0, "served_share"])
    served_after_ten = float(curve.loc[10, "served_share"])
    incremental = int(curve.loc[10, "incremental_orders_per_day"])
    served_share_gain = served_after_ten - served_today
    if served_share_gain <= 0:
        raise ValueError(f"reports/network_{city}_base_curve.csv has no positive N=10 served-share gain")

    # The curve stores shares and the N=10 gain, so their ratio recovers the latent total
    # without rerunning the model. Curve shares are rounded to four decimal places.
    latent_demand = round(incremental / served_share_gain)

    validation = required_csv(Path(f"reports/holdout_validation_{city}.csv"))
    validation = validation[validation["within_km"] == 1.5].groupby("method")["recall"].mean()
    try:
        optimiser_recall = float(validation["optimiser"])
        demand_index_recall = float(validation["top_demand_index"])
    except KeyError as exc:
        raise ValueError(f"reports/holdout_validation_{city}.csv lacks method {exc.args[0]!r}") from exc

    runs = {"base": required_csv(Path(f"reports/network_{city}_base.csv"))}
    for tag in SCENARIOS:
        runs[tag] = required_csv(Path(f"reports/network_{city}_{tag}.csv"))
    areas = robust_areas(runs, ROBUST_KM)
    core_min = max(2, round(len(runs) * 2 / 3))
    core_picks = int((areas["runs"] >= core_min).sum())

    return {
        "City": city.title(),
        "Latent demand/day": f"{latent_demand:,}",
        "% served today": f"{served_today:.1%}",
        "N=10 incremental orders/day": f"+{incremental:,}",
        "% served after N=10": f"{served_after_ten:.1%}",
        "Hold-out recall@1.5km (optimiser / demand-index)": (
            f"{optimiser_recall:.1%} / {demand_index_recall:.1%}"
        ),
        "Core picks": core_picks,
    }


def main() -> None:
    rows = [city_summary(city) for city in CITIES]
    table = md_table(pd.DataFrame(rows))
    text = "\n".join([
        "# Three-city dark-store expansion comparison",
        "",
        table,
        "",
        "Bengaluru has the largest latent demand and the largest absolute pool not served by the current network, "
        "while Pune gains the most coverage from its first ten sites. Bengaluru also has the strongest validation "
        "edge over the demand-index heuristic; Pune is close behind, whereas Hyderabad's small edge is within noise. "
        "Core-pick counts are scenario-stable areas proposed in at least four of the six base-plus-scenario runs.",
        "",
    ])
    output = Path("reports/city_comparison.md")
    output.write_text(text, encoding="utf-8")
    print(f"-> {output}")


if __name__ == "__main__":
    main()
