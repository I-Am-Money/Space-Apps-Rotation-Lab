# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""US rules (Build Spec v4, R2). Owner: Person 3. Pure functions; no network.

  * Alaska and Hawaii: "not supported in this version".
  * Orchard and tree crops: never offered ("not supported yet").
  * Mostly-irrigated counties (NASS Census irrigated share >= threshold in config/assumptions/us_data.yaml)
    default to "irrigated" and the app asks about water first.
  * Suppressed county NASS data -> state average, labelled (done in fetch_nass; surfaced here as a note).
  * Crops without an ERS cost -> the farmer must enter a cost before money numbers show.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS = ROOT / "config" / "assumptions" / "us_data.yaml"
UNSUPPORTED_STATE_MSG = "Alaska and Hawaii are not supported in this version."
ORCHARD_MSG = "Orchards and tree crops are not supported yet."
COST_MSG = "USDA ERS has no cost data for this crop: please enter your cost per acre."


@lru_cache(maxsize=1)
def _cfg() -> dict:
    return yaml.safe_load(ASSUMPTIONS.read_text())


def irrigated_threshold() -> float:
    return float(_cfg()["irrigated_share"]["mostly_irrigated_threshold"]["value"])


def state_supported(state: str | None) -> bool:
    return (state or "").upper() not in set(_cfg()["us_rules"]["unsupported_states"]["value"])


def is_orchard(crop: str) -> bool:
    c = str(crop).lower().strip().replace("_", " ")
    names = _cfg()["us_rules"]["orchard_tree_crops"]["value"]
    return any(c == n or c.rstrip("s") == n.rstrip("s") or c.startswith(n.rstrip("s")) for n in names)


def offered_crops(crops) -> tuple[list[str], list[str]]:
    """(offered, not supported) after removing orchard and tree crops."""
    offered = [c for c in crops if not is_orchard(c)]
    return offered, [c for c in crops if is_orchard(c)]


def water_default(irrigated_share: float | None) -> dict:
    """{"mode": "irrigated"|"rain"|None, "ask_water_first": bool, "reason": str}."""
    if irrigated_share is None:
        return {"mode": None, "ask_water_first": False,
                "reason": "Irrigated share unknown (no NASS Census data): please tell us your water source."}
    if irrigated_share >= irrigated_threshold():
        return {"mode": "irrigated", "ask_water_first": True,
                "reason": f"About {round(irrigated_share * 100)}% of cropland in this county is irrigated "
                          "(USDA Census of Agriculture), so we start from irrigated. Tell us your water supply first."}
    return {"mode": "rain", "ask_water_first": False,
            "reason": f"About {round(irrigated_share * 100)}% of cropland in this county is irrigated, "
                      "so we start from rain only."}


def needs_farmer_cost(crop: str, fips: str | None = None, costs: dict | None = None) -> bool:
    """True when no ERS cost exists for this crop (and the farmer has not given one in `costs`)."""
    if costs and costs.get(crop) is not None:
        return False
    from engine import fetch_ers

    if not fetch_ers.has_ers_cost(crop):
        return True
    return fips is not None and fetch_ers.cost_for_county(fips, crop) is None


def apply(state: str | None, fips: str | None, defaults: dict | None, crops=None,
          farmer_costs: dict | None = None) -> dict:
    """All R2 rules for one US site. `defaults` is fetch_nass.us_defaults() output (or None)."""
    d = defaults or {}
    if not state_supported(state):
        return {"supported": False, "message": UNSUPPORTED_STATE_MSG, "offered": [], "not_supported": [],
                "needs_cost": [], "water": water_default(None), "notes": [UNSUPPORTED_STATE_MSG]}
    pool = list(crops if crops is not None else d.get("crops", []))
    offered, not_supported = offered_crops(pool)
    costs = {**(d.get("costs") or {}), **(farmer_costs or {})}
    needs_cost = [c for c in offered if needs_farmer_cost(c, fips, costs)]
    notes = [f"{c}: {ORCHARD_MSG}" for c in not_supported]
    notes += [f"{c}: {COST_MSG}" for c in needs_cost]
    notes += [f"{k.split(':', 1)[-1]}: {v}" for k, v in (d.get("notes") or {}).items() if "State average" in str(v)]
    return {"supported": True, "message": None, "offered": offered, "not_supported": not_supported,
            "needs_cost": needs_cost, "water": water_default(d.get("irrigated_share")), "notes": notes}
