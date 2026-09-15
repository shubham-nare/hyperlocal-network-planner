from __future__ import annotations

import pandas as pd

POINT_COLUMNS = {"check_point_high_demand": "high_demand", "check_point_low_demand": "low_demand"}
POINT_FIELDS = ["city", "pincode", "office", "point_type", "lat", "lng"]


def check_points_from_sheet(sheet: pd.DataFrame, city: str) -> pd.DataFrame:
    rows = []
    for record in sheet.to_dict("records"):
        for column, point_type in POINT_COLUMNS.items():
            text = record.get(column)
            if not isinstance(text, str) or not text.strip():
                continue
            lat, lng = (float(part) for part in text.split(","))
            rows.append({"city": city, "pincode": record["pincode"], "office": record["office"],
                         "point_type": point_type, "lat": lat, "lng": lng})
    return pd.DataFrame(rows, columns=POINT_FIELDS)


def add_demand_tiers(points: pd.DataFrame, tiers: int = 3) -> pd.DataFrame:
    """Within-city demand tiers (0 = lowest) from demand_index quantiles; ties broken by row order."""

    def tier(s: pd.Series) -> pd.Series:
        if len(s) < tiers:
            return pd.Series(0, index=s.index)
        return pd.qcut(s.rank(method="first"), tiers, labels=False)

    out = points.copy()
    out["demand_tier"] = out.groupby("city")["demand_index"].transform(tier).astype(int)
    return out


def stratified_sample(points: pd.DataFrame, per_stratum: int, seed: int = 42, tiers: int = 3) -> pd.DataFrame:
    """Up to per_stratum points from every (city, demand tier), so validation covers low- to high-demand areas."""
    tiered = add_demand_tiers(points, tiers)
    parts = [
        group.sample(n=min(per_stratum, len(group)), random_state=seed)
        for _, group in tiered.groupby(["city", "demand_tier"], sort=True)
    ]
    return pd.concat(parts).sort_values(["city", "demand_tier", "pincode"]).reset_index(drop=True)
