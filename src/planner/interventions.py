"""Transparent micro-market intervention comparison for v2.

This module does not forecast proprietary customer behaviour.  It combines v1's
calibrated network signals with deliberately visible scenario assumptions to rank
actions worth testing.  Every recommendation carries provenance and guardrails.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InterventionAssumptions:
    zone_extension_capture_rate: float = 0.18
    capacity_addition_fraction: float = 0.20
    assortment_conversion_lift: float = 0.04
    eta_promise_breach_limit: float = 0.10
    minimum_store_breakeven_cover: float = 1.0


@dataclass(frozen=True)
class MicroMarketState:
    city: str
    micro_market: str
    latent_orders_per_day: float
    unserved_orders_per_day: float
    served_share: float
    nearby_capacity_utilisation: float
    nearby_capacity_orders_per_day: float
    new_store_incremental_orders_per_day: float
    new_store_break_even_orders_per_day: float
    eta_breach_rate: float | None = None
    assortment_fit_score: float = 0.5


@dataclass(frozen=True)
class InterventionOption:
    intervention: str
    score: float
    expected_incremental_orders_per_day: float | None
    evidence: tuple[str, ...]
    assumptions: tuple[str, ...]
    guardrails: tuple[str, ...]
    confidence: str


def compare_interventions(state: MicroMarketState, assumptions: InterventionAssumptions = InterventionAssumptions()) -> list[InterventionOption]:
    """Rank testable actions, retaining provenance and uncertainty on every row."""
    _validate_state(state)
    _validate_assumptions(assumptions)
    gap = 1 - state.served_share
    pressure = state.nearby_capacity_utilisation
    demand_scale = min(state.unserved_orders_per_day / state.new_store_break_even_orders_per_day, 3) / 3
    store_cover = state.new_store_incremental_orders_per_day / state.new_store_break_even_orders_per_day
    # Reward how far above break-even the store scenario sits, not just whether it clears it: a store at
    # 2x break-even is a meaningfully more confident bet than one that only just covers its costs.
    store_score = 35 * demand_scale + 30 * pressure + 20 * gap + 20 * min(store_cover, 2)
    if store_cover < assumptions.minimum_store_breakeven_cover:
        store_score *= 0.35

    extension_orders = state.unserved_orders_per_day * assumptions.zone_extension_capture_rate
    extension_score = 45 * gap + 30 * (1 - pressure) + 15 * demand_scale + 10 * (1 - min(store_cover, 1))

    capacity_orders = min(state.unserved_orders_per_day, state.nearby_capacity_orders_per_day * assumptions.capacity_addition_fraction)
    capacity_score = 55 * pressure + 25 * demand_scale + 20 * state.served_share

    assortment_orders = state.unserved_orders_per_day * assumptions.assortment_conversion_lift * state.assortment_fit_score
    assortment_score = 45 * state.assortment_fit_score + 25 * gap + 20 * (1 - pressure) + 10 * demand_scale

    options = [
        InterventionOption(
            "open_dark_store", round(store_score, 1), round(state.new_store_incremental_orders_per_day, 1),
            ("calibrated v1 incremental store orders", "derived city break-even", "calibrated unserved demand", "capacity utilisation scenario"),
            ("uniform store capacity within city",),
            ("break-even coverage", "store ramp-up", "local rent and permits"),
            "medium" if store_cover >= assumptions.minimum_store_breakeven_cover else "low",
        ),
        InterventionOption(
            "extend_service_zone", round(extension_score, 1), round(extension_orders, 1),
            ("calibrated unserved demand", "served-share gap", "capacity utilisation scenario"),
            (f"{assumptions.zone_extension_capture_rate:.0%} capture of unserved calibrated demand",),
            ("ETA breach rate", "cancellation rate", "rider utilisation"), "low",
        ),
        InterventionOption(
            "add_operating_capacity", round(capacity_score, 1), round(capacity_orders, 1),
            ("calibrated unserved demand", "capacity utilisation scenario", "nearby capacity input"),
            (f"{assumptions.capacity_addition_fraction:.0%} additional nearby capacity",),
            ("idle capacity", "contribution per completed order", "ETA breach rate"), "low",
        ),
        InterventionOption(
            "assortment_pilot", round(assortment_score, 1), round(assortment_orders, 1),
            ("calibrated unserved demand", "assortment-fit scenario input"),
            (f"{assumptions.assortment_conversion_lift:.0%} relative conversion lift",),
            ("fill rate", "waste", "contribution per completed order"), "low",
        ),
    ]
    if state.eta_breach_rate is not None:
        eta_score = 50 * (1 - state.eta_breach_rate) + 25 * (1 - pressure) + 25 * state.served_share
        if state.eta_breach_rate >= assumptions.eta_promise_breach_limit:
            eta_score *= 0.2
        options.append(InterventionOption(
            "faster_eta_promise", round(eta_score, 1), None,
            ("observed or simulated ETA-breach rate", "capacity utilisation scenario", "served-share gap"),
            ("ETA response is not forecast from public data",),
            ("ETA breach rate", "cancellation rate", "customer-support contacts"),
            "low" if state.eta_breach_rate >= assumptions.eta_promise_breach_limit else "medium",
        ))
    return sorted(options, key=lambda option: (-option.score, option.intervention))


def _validate_state(state: MicroMarketState) -> None:
    for name in ("latent_orders_per_day", "unserved_orders_per_day", "nearby_capacity_orders_per_day",
                 "new_store_incremental_orders_per_day", "new_store_break_even_orders_per_day"):
        if getattr(state, name) < 0:
            raise ValueError(f"{name} must be non-negative")
    if state.new_store_break_even_orders_per_day <= 0:
        raise ValueError("new_store_break_even_orders_per_day must be positive")
    for name in ("served_share", "nearby_capacity_utilisation", "assortment_fit_score"):
        if not 0 <= getattr(state, name) <= 1:
            raise ValueError(f"{name} must be in [0, 1]")
    if state.eta_breach_rate is not None and not 0 <= state.eta_breach_rate <= 1:
        raise ValueError("eta_breach_rate must be in [0, 1]")


def _validate_assumptions(assumptions: InterventionAssumptions) -> None:
    for name, value in vars(assumptions).items():
        if value < 0 or (name != "minimum_store_breakeven_cover" and value > 1):
            raise ValueError(f"{name} must be non-negative and a probability when applicable")
