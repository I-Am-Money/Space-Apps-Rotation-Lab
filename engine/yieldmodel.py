# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""FAO-33 yield response (Doorenbos & Kassam 1979): 1 - Ya/Ym = Ky (1 - ETa/ETm), plus rotation effects."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np

from engine.crops import A, MILLETS


def season_yield(ym_kg_ha: float, ky: float, eta, etm, rotation_factor=1.0):
    """Ya in kg/ha. eta, etm: season sums (mm), any shape. Ya floored at 0; ETa capped at ETm."""
    eta, etm = np.asarray(eta, float), np.asarray(etm, float)
    ratio = np.clip(eta / np.maximum(etm, 1e-9), 0.0, 1.0)
    rel = np.maximum(1.0 - ky * (1.0 - ratio), 0.0)
    return ym_kg_ha * rel * rotation_factor


def _farm_current_crop():
    path = Path(__file__).resolve().parents[1] / "config" / "farm.yaml"
    return _read_farm_crop(path.stat().st_mtime_ns if path.exists() else None)


@lru_cache(maxsize=2)
def _read_farm_crop(version):
    try:
        import yaml
        doc = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "farm.yaml").read_text()) or {}
        return (doc.get("farm") or {}).get("current_crop")
    except Exception:
        return None


def previous_crop(params: dict | None = None):
    """The crop grown the year before the plan starts: farm.current_crop in config/farm.yaml (a farm fact, Local
    input), unless params["previous_crop"] says otherwise. The farm grows rice every year today, so a plan that
    starts with rice starts with rice after rice. None means year 1 has no predecessor."""
    if params and "previous_crop" in params:
        return params["previous_crop"]
    return _farm_current_crop()


def _pair_factor(prev, cur, params) -> float:
    if prev == "pigeonpea":
        if cur == "rice":
            return A(params, "rotation.rice_after_pigeonpea")
        if cur in MILLETS:
            return A(params, "rotation.millet_after_pigeonpea")
        if cur == "pigeonpea":
            return A(params, "rotation.pigeonpea_after_pigeonpea")
    elif prev == "rice" and cur == "rice":
        return A(params, "rotation.rice_after_rice")
    elif prev in MILLETS and cur in MILLETS:
        return A(params, "rotation.millet_after_millet")
    return 1.0


def rotation_factor(plan: Sequence[str], params: dict | None = None) -> np.ndarray:
    """Per-year yield multiplier from the previous year's crop. Year 1 follows previous_crop() (rice on this farm)."""
    seq = [previous_crop(params)] + list(plan)
    return np.array([_pair_factor(seq[i], seq[i + 1], params) for i in range(len(plan))], float)


def nitrogen_credit_kg_ha(plan: Sequence[str], params: dict | None = None) -> np.ndarray:
    """Nitrogen credit (kg N/ha) to rice or millet following pigeon pea (year 1 follows previous_crop())."""
    seq = [previous_crop(params)] + list(plan)
    n = np.zeros(len(plan))
    for i in range(len(plan)):
        if seq[i] == "pigeonpea" and (seq[i + 1] == "rice" or seq[i + 1] in MILLETS):
            n[i] = A(params, "rotation.n_credit_after_pigeonpea")
    return n
