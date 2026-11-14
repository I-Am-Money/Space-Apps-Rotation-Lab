"""FAO-33 yield response (Doorenbos & Kassam 1979): 1 - Ya/Ym = Ky (1 - ETa/ETm), plus rotation effects."""
from __future__ import annotations

from typing import Sequence

import numpy as np

from engine.crops import A, MILLETS


def season_yield(ym_kg_ha: float, ky: float, eta, etm, rotation_factor=1.0):
    """Ya in kg/ha. eta, etm: season sums (mm), any shape. Ya floored at 0; ETa capped at ETm."""
    eta, etm = np.asarray(eta, float), np.asarray(etm, float)
    ratio = np.clip(eta / np.maximum(etm, 1e-9), 0.0, 1.0)
    rel = np.maximum(1.0 - ky * (1.0 - ratio), 0.0)
    return ym_kg_ha * rel * rotation_factor


def rotation_factor(plan: Sequence[str], params: dict | None = None) -> np.ndarray:
    """Per-year yield multiplier from the previous year's crop (year 1 has no predecessor: 1.0)."""
    f = np.ones(len(plan))
    for i in range(1, len(plan)):
        prev, cur = plan[i - 1], plan[i]
        if prev == "pigeonpea":
            if cur == "rice":
                f[i] = A(params, "rotation.rice_after_pigeonpea")
            elif cur in MILLETS:
                f[i] = A(params, "rotation.millet_after_pigeonpea")
            elif cur == "pigeonpea":
                f[i] = A(params, "rotation.pigeonpea_after_pigeonpea")
        elif prev == "rice" and cur == "rice":
            f[i] = A(params, "rotation.rice_after_rice")
        elif prev in MILLETS and cur in MILLETS:
            f[i] = A(params, "rotation.millet_after_millet")
    return f


def nitrogen_credit_kg_ha(plan: Sequence[str], params: dict | None = None) -> np.ndarray:
    """Nitrogen credit (kg N/ha) to rice or millet following pigeon pea."""
    n = np.zeros(len(plan))
    for i in range(1, len(plan)):
        if plan[i - 1] == "pigeonpea" and (plan[i] == "rice" or plan[i] in MILLETS):
            n[i] = A(params, "rotation.n_credit_after_pigeonpea")
    return n
