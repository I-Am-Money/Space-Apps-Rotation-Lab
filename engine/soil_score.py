# AI use: this file was written by Claude Code (Anthropic) under the team's direction, then reviewed by the team. See AI_USE.md.
"""Soil Health Score, 0 to 100 (Build Spec v4, R11). Owner: Person 3.

Rule-based score from the four NRCS soil health principles (minimize disturbance, maximize soil cover,
maximize biodiversity, maximize continuous living roots). Not a soil test.

    base  = 100 * (w_cover*cover + w_roots*roots + w_diversity*diversity + w_residue*residue) / sum(w)
    score = clip(base - repetition_penalty + tillage_points + history_points, 0, 100)

Components (each 0 to 1, averaged over the years of the plan):
  roots     share of the year with a living cash crop or cover crop (season lengths, capped at 365 days)
  cover     roots + the rest of the year covered by residue left on the surface
            (residue dry matter / full-cover amount, times the share tillage leaves on the surface)
  diversity species part (distinct cash + cover species) and legume part (share of seasons with a legume)
  residue   residue carbon input per year / the full-credit amount
            residue C (kg/ha) = yield (kg/ha) * dry matter * (1 - HI) / HI * carbon fraction  (+ cover crop biomass C)

Every weight, target and crop value is in config/assumptions.yaml under soil_score, with a source note or
"team to verify". If yields are missing, residue-based parts are left out (not invented) and noted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS_PATH = ROOT / "config" / "assumptions" / "recommend.yaml"
LABEL = "Rule-based score from NRCS soil health principles. Not a soil test."

# Common names and earlier crop ids mapped to the ids in assumptions.yaml.
ALIASES = {
    "corn": "maize", "corn_grain": "maize", "maize_grain": "maize",
    "soybeans": "soybean", "soy": "soybean", "soya": "soybean",
    "wheat": "wheat_winter", "winter_wheat": "wheat_winter", "spring_wheat": "wheat_spring",
    "sorghum_grain": "sorghum", "jowar": "sorghum", "milo": "sorghum",
    "bajra": "pearl_millet", "millet": "pearl_millet",
    "groundnut": "peanut", "peanuts": "peanut", "tur": "pigeonpea", "pigeon_pea": "pigeonpea",
    "paddy": "rice", "cotton_upland": "cotton", "upland_cotton": "cotton",
    "rye": "cereal_rye", "winter_rye": "cereal_rye", "clover": "crimson_clover", "vetch": "hairy_vetch",
    "oat_cover": "oats_cover",
}
TILLAGE = ("no_till", "reduced", "conventional")
_TILLAGE_ALIASES = {"no-till": "no_till", "notill": "no_till", "none": "no_till", "strip_till": "reduced",
                    "minimum": "reduced", "min_till": "reduced", "conservation": "reduced",
                    "conventional_till": "conventional", "plow": "conventional", "full": "conventional"}


@dataclass
class SoilScore:
    score: float                       # 0 to 100
    components: dict                   # cover, roots, diversity, residue: 0 to 1 (None if not computable)
    points: dict                       # base, repetition, tillage, history (score points)
    residue_c_t_ha_yr: float | None    # mean residue carbon input per year
    label: str = LABEL
    badge: str = "Assumption"
    notes: list = field(default_factory=list)
    placeholders: list = field(default_factory=list)   # crops scored with fallback ("Placeholder") values

    def as_dict(self) -> dict:
        return {"score": self.score, "components": dict(self.components), "points": dict(self.points),
                "residue_c_t_ha_yr": self.residue_c_t_ha_yr, "label": self.label, "badge": self.badge,
                "notes": list(self.notes), "placeholders": list(self.placeholders)}


# ---------------------------------------------------------------- assumptions

def _mtime():
    return ASSUMPTIONS_PATH.stat().st_mtime_ns


@lru_cache(maxsize=2)
def _section(version) -> dict:
    return (yaml.safe_load(ASSUMPTIONS_PATH.read_text()) or {})["soil_score"]


def section() -> dict:
    return _section(_mtime())


def _v(node):
    return node["value"] if isinstance(node, dict) and "value" in node else node


def norm(name: str | None) -> str | None:
    if name is None:
        return None
    k = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    return ALIASES.get(k, k)


def crop_info(crop: str, cover: bool = False) -> tuple[dict, bool]:
    """(values, is_placeholder). Cash crops: legume, living_days, harvest_index, dry_matter.
    Cover crops: legume, living_days, biomass_t_ha. Unknown crops use the unknown_crop fallback."""
    s = section()
    c = norm(crop)
    table = s["cover_crops"] if cover else s["crops"]
    if c in table:
        return {k: _v(v) for k, v in table[c].items()}, False
    if not cover and c in s["cover_crops"]:          # a cover crop name given as a cash crop
        return crop_info(c, cover=True)[0] | {"harvest_index": None, "dry_matter": None}, False
    u = {k: _v(v) for k, v in s["unknown_crop"].items()}
    if cover:
        return {"legume": False, "living_days": u["living_days"], "biomass_t_ha": u["cover_biomass_t_ha"]}, True
    return {"legume": False, "living_days": u["living_days"], "harvest_index": u["harvest_index"],
            "dry_matter": u["dry_matter"]}, True


def residue_carbon_kg_ha(crop: str, yield_kg_ha: float) -> float:
    """Above-ground residue carbon (kg C/ha) from a harvested yield:
    yield * dry_matter * (1 - HI) / HI * carbon_fraction."""
    info, _ = crop_info(crop)
    hi, dm = info.get("harvest_index"), info.get("dry_matter")
    if not hi or dm is None or yield_kg_ha is None:
        return 0.0
    cf = _v(section()["residue"]["carbon_fraction"])
    return float(yield_kg_ha) * dm * (1.0 - hi) / hi * cf


def cover_crop_carbon_kg_ha(cover: str) -> float:
    info, _ = crop_info(cover, cover=True)
    return float(info["biomass_t_ha"]) * 1000.0 * _v(section()["residue"]["carbon_fraction"])


# ---------------------------------------------------------------- input shapes

def _years(crops) -> list[list[str]]:
    """Accept ['maize','soybean',...], [['wheat_winter','soybean'], ...] or 'wheat_winter+soybean' strings."""
    out = []
    for y in crops:
        if y is None:
            out.append([])
        elif isinstance(y, str):
            out.append([p for p in (q.strip() for q in y.replace("/", "+").split("+")) if p])
        else:
            out.append([str(p) for p in y if p])
    return out


def _covers(cover_crops, n) -> list[str | None]:
    if cover_crops is None:
        return [None] * n
    if isinstance(cover_crops, str):
        return [cover_crops] * n
    cc = [None if (c is None or str(c).strip().lower() in ("", "none")) else c for c in cover_crops]
    return (cc + [None] * n)[:n]


def _yields(yields, years) -> list[list[float | None]] | None:
    """Per year, per season yields in kg/ha. Accepts list per year (number or list) or dict crop -> kg/ha."""
    if yields is None:
        return None
    if isinstance(yields, dict):
        lookup = {norm(k): v for k, v in yields.items()}
        return [[lookup.get(norm(c)) for c in y] for y in years]
    out = []
    for i, y in enumerate(years):
        v = yields[i] if i < len(yields) else None
        if isinstance(v, (list, tuple)):
            out.append([None if x is None else float(x) for x in v] + [None] * (len(y) - len(v)))
        else:
            out.append([None if v is None else float(v)] + [None] * (len(y) - 1))
    return out


def _tillage(history, tillage) -> str:
    t = tillage or (history or {}).get("tillage")
    if t is None:
        return _v(section()["tillage"]["default"])
    k = str(t).strip().lower().replace(" ", "_")
    k = _TILLAGE_ALIASES.get(k, _TILLAGE_ALIASES.get(k.replace("_", "-"), k))
    return k if k in TILLAGE else _v(section()["tillage"]["default"])


def _truthy(x) -> bool:
    if isinstance(x, str):
        return x.strip().lower() in ("yes", "true", "y", "1", "some", "often", "severe", "moderate")
    return bool(x)


# ---------------------------------------------------------------- score

def repetition_count(crops) -> tuple[int, bool]:
    """(back-to-back repeats of the same cash crop in season order, is_monoculture)."""
    seq = [norm(c) for y in _years(crops) for c in y]
    repeats = sum(1 for a, b in zip(seq, seq[1:]) if a == b)
    return repeats, len(seq) >= 2 and len(set(seq)) == 1


def soil_score(crops: Sequence, cover_crops=None, yields=None, history: dict | None = None,
               tillage: str | None = None) -> SoilScore:
    """Soil Health Score for one rotation.

    crops: one entry per year; each a crop id or a list of 1-2 crop ids (two seasons in one year).
    cover_crops: None, one cover crop id for every year, or one entry (id or None) per year.
    yields: kg/ha per year (number, or list per season) or dict crop -> kg/ha. Optional.
    history: farmer's field history, keys tillage, erosion, waterlogging, salinity (cover_crops is recorded only).
    """
    s = section()
    years = _years(crops)
    n = len(years)
    if n == 0:
        raise ValueError("soil_score needs at least one year of crops")
    covers = _covers(cover_crops, n)
    ylds = _yields(yields, years)
    till = _tillage(history, tillage)
    notes, placeholders = [], []

    residue_left = _v(s["tillage"]["residue_left_on_surface"][till])
    full_cover_dm = _v(s["residue"]["dm_for_full_cover_t_ha"]) * 1000.0
    full_c = _v(s["residue"]["c_for_full_credit_t_ha_yr"]) * 1000.0

    roots_y, cover_y, carbon_y = [], [], []
    species, seasons, legume_seasons = set(), 0, 0
    for i, yr in enumerate(years):
        days, c_kg, resid_dm = 0.0, 0.0, 0.0
        for j, crop in enumerate(yr):
            info, ph = crop_info(crop)
            if ph:
                placeholders.append(norm(crop))
            days += info["living_days"]
            species.add(norm(crop))
            seasons += 1
            legume_seasons += bool(info["legume"])
            y = None if ylds is None else ylds[i][j]
            if y is not None:
                c = residue_carbon_kg_ha(crop, y)
                c_kg += c
                resid_dm += c / _v(s["residue"]["carbon_fraction"])
        cc = covers[i]
        if cc:
            info, ph = crop_info(cc, cover=True)
            if ph:
                placeholders.append(norm(cc))
            days += info["living_days"]
            species.add(norm(cc))
            seasons += 1
            legume_seasons += bool(info["legume"])
            c_kg += cover_crop_carbon_kg_ha(cc)
            resid_dm += info["biomass_t_ha"] * 1000.0
        roots = min(days / 365.0, 1.0)
        roots_y.append(roots)
        carbon_y.append(c_kg)
        surface = min(resid_dm * residue_left / full_cover_dm, 1.0) if full_cover_dm > 0 else 0.0
        cover_y.append(min(roots + (1.0 - roots) * surface, 1.0))

    have_yields = ylds is not None and all(v is not None for row in ylds for v in row)
    if not have_yields:
        notes.append("No yields given: residue carbon and residue cover are left out of the score, not guessed.")
    d = s["diversity"]
    species_part = min((len(species) - 1) / max(_v(d["species_for_full_credit"]) - 1, 1), 1.0)
    legume_part = min((legume_seasons / max(seasons, 1)) / _v(d["legume_share_for_full_credit"]), 1.0)
    lp = _v(d["legume_part"])
    comp = {
        "roots": sum(roots_y) / n,
        "cover": (sum(cover_y) / n) if have_yields else None,
        "diversity": (1 - lp) * species_part + lp * legume_part,
        "residue": min(sum(carbon_y) / n / full_c, 1.0) if have_yields else None,
    }
    if not have_yields:          # cover without residue is just living cover; count it as that, labeled
        comp["cover"] = comp["roots"]
        notes.append("Soil cover counts living crops and cover crops only (no residue) because yields are missing.")

    w = {k: _v(v) for k, v in s["weights"].items()}
    used = {k: w[k] for k, v in comp.items() if v is not None}
    base = 100.0 * sum(w[k] * comp[k] for k in used) / sum(used.values())

    repeats, mono = repetition_count(years)
    rp = s["repetition"]
    rep_pts = -(repeats * _v(rp["points_per_repeat"]) + (_v(rp["monoculture_extra_points"]) if mono else 0))
    till_pts = _v(s["tillage"]["points"][till])
    hist_pts = 0.0
    for k in ("erosion", "waterlogging", "salinity"):
        if history and _truthy(history.get(k)):
            hist_pts += _v(s["history_points"][k])
    if mono:
        notes.append("Same cash crop every season: continuous single-crop penalty applied.")
    score = max(0.0, min(100.0, base + rep_pts + till_pts + hist_pts))
    return SoilScore(
        score=round(score, 1), components=comp,
        points={"base": round(base, 2), "repetition": rep_pts, "tillage": till_pts, "history": hist_pts,
                "tillage_used": till},
        residue_c_t_ha_yr=(sum(carbon_y) / n / 1000.0) if have_yields else None,
        notes=notes, placeholders=sorted(set(placeholders)),
        badge="Placeholder" if placeholders else "Assumption")


def score_result(rotation_result, history: dict | None = None) -> SoilScore:
    """Convenience for Person 1: score an api.RotationResult-like object (crops, cover_crops, yields_by_year).

    yields_by_year: one entry per year (list, or dict in year order). Each entry is a number or a numpy array
    of scenario yields (one season), or a list/tuple/dict with one number-or-array per season. Arrays are
    averaged over scenarios.
    """
    import numpy as np

    crops = getattr(rotation_result, "crops")
    covers = getattr(rotation_result, "cover_crops", None)
    yb = getattr(rotation_result, "yields_by_year", None)
    ylds = None
    if yb is not None:
        rows = list(yb.values()) if isinstance(yb, dict) else list(yb)
        ylds = []
        for r in rows:
            if isinstance(r, dict):
                r = list(r.values())
            if isinstance(r, (list, tuple)):
                ylds.append([float(np.mean(x)) for x in r])
            else:
                ylds.append(float(np.mean(r)))
    return soil_score(crops, covers, ylds, history)


def score_many(rotations: Iterable[dict], history: dict | None = None) -> list[SoilScore]:
    """Score many rotations given as dicts with keys crops, cover_crops (optional), yields (optional)."""
    return [soil_score(r["crops"], r.get("cover_crops"), r.get("yields"), history) for r in rotations]
