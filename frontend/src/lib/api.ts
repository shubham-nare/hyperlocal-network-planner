const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type CitySummary = {
  city: string;
  hex_count: number;
  population: number;
  store_count: number;
};

export type Hex = {
  h3: string;
  lat: number;
  lng: number;
  population: number;
  demand_index: number;
  in_core: boolean;
  geometry: GeoJSON.Geometry;
};

export type RecommendedSite = {
  rank: number;
  h3: string;
  lat: number;
  lng: number;
  locality: string | null;
  pincode: string | null;
  demand_index: number;
  site_orders_per_day: number;
  incremental_orders_per_day: number;
  new_coverage_orders: number;
  capacity_relief_orders: number;
  breakeven_cover: number;
  competitor_stores_reaching_hex: number;
};

export type RentShockCalibration = {
  city: string;
  gross_profit_per_order: number;
  variable_cost_per_order: number;
  other_fixed_cost_per_day: number;
  rent_per_sqft_month: number;
  size_sqft: number;
};

export type RentShockResult = {
  id: number;
  baseline_rent_per_sqft_month: number;
  shocked_rent_per_sqft_month: number;
  baseline_breakeven_orders_per_day: number;
  shocked_breakeven_orders_per_day: number;
  breakeven_increase_pct: number;
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`${path} -> ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`${path} -> ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  cities: () => get<CitySummary[]>("/cities"),
  hexes: (city: string, limit = 1500) => get<Hex[]>(`/cities/${city}/hexes?limit=${limit}`),
  recommendedSites: (city: string) => get<RecommendedSite[]>(`/cities/${city}/recommended-sites`),
  rentShockCalibration: (city: string) => get<RentShockCalibration>(`/scenarios/calibration/${city}`),
  runRentShock: (body: {
    city: string;
    rent_per_sqft_month: number;
    size_sqft: number;
    other_fixed_cost_per_day: number;
    gross_profit_per_order: number;
    variable_cost_per_order: number;
    shock_pct: number;
  }) => post<RentShockResult>("/scenarios/rent-shock", body),
};
