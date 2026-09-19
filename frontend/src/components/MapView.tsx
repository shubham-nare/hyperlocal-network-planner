"use client";

import { useEffect, useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import { api, type CitySummary, type Hex, type RecommendedSite, type RentShockCalibration } from "@/lib/api";

const CITY_CENTERS: Record<string, { longitude: number; latitude: number; zoom: number }> = {
  hyderabad: { longitude: 78.48, latitude: 17.4, zoom: 10.5 },
  bengaluru: { longitude: 77.59, latitude: 12.97, zoom: 10.5 },
  pune: { longitude: 73.85, latitude: 18.52, zoom: 10.5 },
};

function demandColor(value: number, min: number, max: number): [number, number, number, number] {
  const t = max > min ? (value - min) / (max - min) : 0;
  // low demand -> dark blue, high demand -> red-orange, matching the reports/*.png convention elsewhere in this project
  const r = Math.round(30 + t * 200);
  const g = Math.round(40 + (1 - Math.abs(t - 0.5) * 2) * 80);
  const b = Math.round(120 - t * 100);
  return [r, g, Math.max(b, 20), 140];
}

export default function MapView() {
  const [cities, setCities] = useState<CitySummary[]>([]);
  const [city, setCity] = useState<string>("hyderabad");
  const [hexes, setHexes] = useState<Hex[]>([]);
  const [sites, setSites] = useState<RecommendedSite[]>([]);
  const [selectedSite, setSelectedSite] = useState<RecommendedSite | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [calibration, setCalibration] = useState<RentShockCalibration | null>(null);
  const [shockPct, setShockPct] = useState(0.25);
  const [rentResult, setRentResult] = useState<Awaited<ReturnType<typeof api.runRentShock>> | null>(null);
  const [rentError, setRentError] = useState<string | null>(null);

  useEffect(() => {
    api.cities().then(setCities).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setSelectedSite(null);
    setRentResult(null);
    Promise.all([api.hexes(city), api.recommendedSites(city), api.rentShockCalibration(city)])
      .then(([h, s, cal]) => {
        setHexes(h);
        setSites(s);
        setCalibration(cal);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [city]);

  const [demandMin, demandMax] = useMemo(() => {
    if (hexes.length === 0) return [0, 1];
    const values = hexes.map((h) => h.demand_index);
    return [Math.min(...values), Math.max(...values)];
  }, [hexes]);

  const layers = [
    new GeoJsonLayer({
      id: "hexes",
      data: hexes.map((h) => ({ type: "Feature" as const, properties: h, geometry: h.geometry })),
      getFillColor: (f: { properties: Hex }) => demandColor(f.properties.demand_index, demandMin, demandMax),
      getLineColor: [255, 255, 255, 30],
      lineWidthMinPixels: 1,
      pickable: true,
    }),
    new ScatterplotLayer<RecommendedSite>({
      id: "recommended-sites",
      data: sites,
      getPosition: (s) => [s.lng, s.lat],
      getRadius: (s) => 80 + Math.sqrt(Math.max(s.incremental_orders_per_day, 0)) * 4,
      getFillColor: [255, 200, 0, 220],
      getLineColor: [20, 20, 20, 255],
      lineWidthMinPixels: 1,
      pickable: true,
      onClick: (info: PickingInfo<RecommendedSite>) => info.object && setSelectedSite(info.object),
    }),
  ];

  function getTooltip(info: PickingInfo) {
    if (info.layer?.id === "recommended-sites" && info.object) {
      const s = info.object as RecommendedSite;
      return { text: `#${s.rank} ${s.locality ?? s.h3}\n${s.site_orders_per_day.toFixed(0)} orders/day\n+${s.incremental_orders_per_day.toFixed(0)} incremental` };
    }
    if (info.layer?.id === "hexes" && info.object) {
      const h = (info.object as GeoJSON.Feature).properties as Hex;
      return { text: `demand index ${h.demand_index.toFixed(1)}\npopulation ${h.population.toFixed(0)}` };
    }
    return null;
  }

  async function submitRentShock() {
    if (!calibration) return;
    setRentError(null);
    try {
      const result = await api.runRentShock({
        city,
        rent_per_sqft_month: calibration.rent_per_sqft_month,
        size_sqft: calibration.size_sqft,
        other_fixed_cost_per_day: calibration.other_fixed_cost_per_day,
        gross_profit_per_order: calibration.gross_profit_per_order,
        variable_cost_per_order: calibration.variable_cost_per_order,
        shock_pct: shockPct,
      });
      setRentResult(result);
    } catch (e) {
      setRentError(String(e));
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh", width: "100vw", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ position: "relative", flex: 1 }}>
        <DeckGL
          initialViewState={CITY_CENTERS[city]}
          controller
          layers={layers}
          getTooltip={getTooltip}
          style={{ position: "absolute", inset: "0", background: "#111" }}
        />
        <div style={{ position: "absolute", top: 12, left: 12, color: "#eee", background: "rgba(0,0,0,0.55)", padding: "8px 12px", borderRadius: 6, fontSize: 13 }}>
          <strong>Hyperlocal Network Planner</strong>
          <div>Hexes colored by demand index; gold dots are recommended new sites (size = incremental orders/day).</div>
          {loading && <div>Loading real project data...</div>}
          {error && <div style={{ color: "#f88" }}>Error: {error}</div>}
        </div>
      </div>
      <div style={{ width: 320, background: "#1b1b1f", color: "#eee", padding: 16, overflowY: "auto" }}>
        <label>
          City
          <select value={city} onChange={(e) => setCity(e.target.value)} style={{ width: "100%", marginTop: 4, marginBottom: 16, padding: 6 }}>
            {(cities.length ? cities.map((c) => c.city) : Object.keys(CITY_CENTERS)).map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>
        {cities.length > 0 && (
          <div style={{ fontSize: 13, opacity: 0.8, marginBottom: 16 }}>
            {cities.find((c) => c.city === city) && (
              <>
                {cities.find((c) => c.city === city)!.hex_count} hexes,{" "}
                {cities.find((c) => c.city === city)!.store_count} stores,{" "}
                {cities.find((c) => c.city === city)!.population.toLocaleString()} people
              </>
            )}
          </div>
        )}

        <h3 style={{ marginBottom: 8 }}>Selected site</h3>
        {selectedSite ? (
          <div style={{ fontSize: 13, lineHeight: 1.6 }}>
            <div><strong>#{selectedSite.rank} {selectedSite.locality ?? selectedSite.h3}</strong> ({selectedSite.pincode})</div>
            <div>Orders/day: {selectedSite.site_orders_per_day.toFixed(0)}</div>
            <div>Incremental: {selectedSite.incremental_orders_per_day.toFixed(0)}</div>
            <div>New coverage: {selectedSite.new_coverage_orders.toFixed(0)}</div>
            <div>Capacity relief: {selectedSite.capacity_relief_orders.toFixed(0)}</div>
            <div>Break-even cover: {selectedSite.breakeven_cover.toFixed(2)}x</div>
            <div>Competitor stores reaching hex: {selectedSite.competitor_stores_reaching_hex}</div>
          </div>
        ) : (
          <div style={{ fontSize: 13, opacity: 0.6 }}>Click a gold dot on the map.</div>
        )}

        <h3 style={{ marginTop: 24, marginBottom: 8 }}>Rent shock scenario</h3>
        {calibration ? (
          <div style={{ fontSize: 13 }}>
            <div style={{ opacity: 0.7, marginBottom: 8 }}>
              Calibrated base rent Rs.{calibration.rent_per_sqft_month}/sqft/month, gross profit Rs.{calibration.gross_profit_per_order.toFixed(0)}/order.
            </div>
            <label>
              Rent shock: {(shockPct * 100).toFixed(0)}%
              <input
                type="range" min={-0.5} max={1} step={0.05} value={shockPct}
                onChange={(e) => setShockPct(Number(e.target.value))}
                style={{ width: "100%" }}
              />
            </label>
            <button onClick={submitRentShock} style={{ marginTop: 8, width: "100%", padding: 8 }}>
              Run scenario
            </button>
            {rentError && <div style={{ color: "#f88", marginTop: 8 }}>{rentError}</div>}
            {rentResult && (
              <div style={{ marginTop: 12, lineHeight: 1.6 }}>
                <div>Break-even: {rentResult.baseline_breakeven_orders_per_day.toFixed(0)} to {rentResult.shocked_breakeven_orders_per_day.toFixed(0)} orders/day</div>
                <div>Change: {(rentResult.breakeven_increase_pct * 100).toFixed(1)}%</div>
              </div>
            )}
          </div>
        ) : (
          <div style={{ fontSize: 13, opacity: 0.6 }}>Loading calibration...</div>
        )}
      </div>
    </div>
  );
}
