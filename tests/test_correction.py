# AI use: this file was written by Claude Code (Anthropic) under the team's direction, then reviewed by the team. See AI_USE.md.
"""Tests for engine/correction.py (Person 3, R12)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import correction as cr
from engine import hindcast as hc

YEARS = np.arange(1990, 2020)


def _county(seed=42):
    rng = np.random.default_rng(seed)
    rain = rng.uniform(250, 600, len(YEARS))
    heat = rng.integers(0, 30, len(YEARS)).astype(float)
    rel = np.clip(0.5 + rain / 1200 - heat / 200, 0, 1)
    # Actual has a trend and a heat effect the model under-counts, plus noise.
    actual = 7000 + 90 * (YEARS - 1990) + 5000 * (rel - 0.75) - 40 * heat + rng.normal(0, 150, len(YEARS))
    return hc.hindcast_series("C", "maize", YEARS, actual, rel, rain, heat, holdout=8, min_years=20)


def test_fit_recovers_exact_linear_bias():
    rain = 400 + 150 * np.sin(np.arange(15.0))       # not collinear with year
    heat = np.arange(15.0) % 7
    year = np.arange(2000, 2015)
    modeled = np.full(15, 8000.0)
    actual = modeled + 100 + 2 * rain - 30 * heat + 50 * (year - 2000)
    c = cr.fit(actual, modeled, rain, heat, year)
    assert c.coef == pytest.approx([100, 2, -30, 50], abs=1e-6)
    assert c.apply(modeled, rain, heat, year) == pytest.approx(actual)


def test_correction_never_trains_on_held_out_years(monkeypatch):
    h = _county()
    seen = {}
    real_fit = cr.fit

    def spy(actual, modeled, rain, heat, year):
        seen["years"] = list(np.asarray(year))
        return real_fit(actual, modeled, rain, heat, year)

    monkeypatch.setattr(cr, "fit", spy)
    e = cr.evaluate(h)
    assert e.corrected_used
    assert seen["years"] == list(YEARS[:-8]) and not set(seen["years"]) & set(h.test_years)

    # Changing held-out actuals changes neither the fit nor the training numbers.
    h2 = _county()
    h2.actual = list(np.asarray(h2.actual) + np.where(np.asarray(h2.train_mask), 0, 5000.0))
    e2 = cr.evaluate(h2)
    assert e2.coef == pytest.approx(e.coef) and e2.mae_corrected != e.mae_corrected


def test_correction_reduces_held_out_error_on_trending_county():
    e = cr.evaluate(_county())
    assert e.n_train == 22 and e.n_test == 8
    assert e.mae_corrected < e.mae      # the year term removes the trend the raw model cannot see


def test_too_few_training_years_skips_correction():
    h = hc.hindcast_series("C", "maize", YEARS[:15], np.linspace(5000, 6000, 15) + np.sin(np.arange(15)) * 300,
                           0.8 + 0.1 * np.cos(np.arange(15)), np.full(15, 400.0), np.arange(15.0), holdout=8, min_years=10)
    e = cr.evaluate(h)
    assert not e.corrected_used and e.r_corrected is None and any("not fitted" in n for n in e.notes)


def test_validation_summary_shape_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "RESULTS_PATH", tmp_path / "results.csv")
    sites = hc.validation_sites()[:2]
    table = cr.run_validation(sites, weather_loader=lambda s: None, yield_loader=lambda f, c: None)
    assert len(table) == sum(len(s["crops"]) for s in sites)
    assert set(["site", "crop", "r", "mae", "r_corrected", "mae_corrected"]) <= set(table.columns)
    assert (table.status == "no weather").all() and table.r.isna().all()


def test_validation_summary_reads_results_file(tmp_path, monkeypatch):
    p = tmp_path / "results.csv"
    pd.DataFrame([{"site": "IA-story", "crop": "maize", "r": 0.5, "mae": 900, "r_corrected": 0.6,
                   "mae_corrected": 500, "status": "ok", "fips": "19169"}]).to_csv(p, index=False)
    monkeypatch.setattr(hc, "RESULTS_PATH", p)
    vs = cr.validation_summary()
    assert list(vs.table.columns) == cr.COLUMNS and vs.table.fips.iloc[0] == "19169"
    assert len(vs.sites) >= 10


def test_validation_summary_without_results_never_fetches(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "RESULTS_PATH", tmp_path / "missing.csv")
    monkeypatch.setattr(hc, "load_site_weather", lambda s: (_ for _ in ()).throw(AssertionError("fetched")))
    vs = cr.validation_summary()
    assert (vs.table.status == "validation not run yet").all() and len(vs.table) >= 10
