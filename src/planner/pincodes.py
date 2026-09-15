from __future__ import annotations

import geopandas as gpd
import pandas as pd


def load_boundaries(path: str) -> gpd.GeoDataFrame:
    boundaries = gpd.read_file(path)
    boundaries["geometry"] = boundaries.geometry.make_valid()
    boundaries["pincode"] = pd.to_numeric(boundaries["pincode"], errors="coerce").astype("Int64")
    return boundaries.dropna(subset=["pincode"]).to_crs("EPSG:4326")


def assign_hexes_to_pincodes(hexes: gpd.GeoDataFrame, boundaries: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Each hex takes the pincode polygon containing its centroid; hexes whose centroid falls in no polygon
    take the nearest polygon and are flagged in `pincode_by_nearest`."""
    out = hexes.copy()
    utm = out.estimate_utm_crs()
    centroids = gpd.GeoDataFrame({"h3": out["h3"]}, geometry=out.to_crs(utm).centroid, crs=utm)
    polys = boundaries[["pincode", "officename", "district", "geometry"]].to_crs(utm)

    hit = gpd.sjoin(centroids, polys, predicate="within", how="left")
    hit = hit[~hit.index.duplicated()]  # a centroid on a shared edge can match two polygons
    missing = hit["pincode"].isna()
    if missing.any():
        near = gpd.sjoin_nearest(centroids[missing], polys, how="left")
        near = near[~near.index.duplicated()]
        hit.loc[missing, ["pincode", "officename", "district"]] = near[["pincode", "officename", "district"]].to_numpy()

    out["pincode"] = pd.array(hit["pincode"].to_numpy(), dtype="Int64")
    out["pincode_office"] = hit["officename"].to_numpy()
    out["pincode_district"] = hit["district"].to_numpy()
    out["pincode_by_nearest"] = missing.to_numpy()
    return out
