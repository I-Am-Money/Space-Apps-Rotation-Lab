# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Smoke tests for ui/recommendations.py and ui/measure.py: run each page headlessly and check what a farmer sees."""
import sys

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, "tests")


def _rec_app():
    import sys; sys.path.insert(0, "tests")
    import ui_fixtures as fx
    from ui import recommendations
    recommendations.render(fx.site(), fx.inputs(), currency="USD", area_unit="ha", simulate=fx.simulate, scenarios=list(range(10)), crops=fx.CROPS)


def _rec_acre_app():
    import sys; sys.path.insert(0, "tests")
    import ui_fixtures as fx
    from ui import recommendations
    recommendations.render(fx.site(), fx.inputs(), currency="USD", area_unit="acre", simulate=fx.simulate, scenarios=list(range(10)), crops=fx.CROPS)


def _rec_example_app():
    import sys; sys.path.insert(0, "tests")
    import ui_fixtures as fx
    from ui import recommendations
    from engine import optimize as opt
    recommendations.render(fx.site(), fx.inputs(plan=("maize",) * 4), currency="USD", crops=["maize", "sorghum"], simulate=opt._stand_in_simulate, scenarios=list(range(10)))


def _rec_input_needed_app():
    import sys; sys.path.insert(0, "tests")
    import ui_fixtures as fx
    from ui import recommendations
    recommendations.render(fx.site(), fx.inputs(plan=("quinoa",) * 4), simulate=fx.simulate, scenarios=list(range(10)), crops=["maize"])


def _measure_app():
    import sys; sys.path.insert(0, "tests")
    import ui_fixtures as fx
    from ui import measure
    measure.render(fx.site(), fx.inputs(mode="irrigated", normal=400.0), {"bad_year": 0.0}, simulate=fx.simulate, scenarios=list(range(10)), crops=fx.CROPS)


def _text(at):
    """Everything a farmer can read: markdown, captions, headers, warnings, info and metrics."""
    parts = []
    for group in (at.markdown, at.caption, at.header, at.subheader, at.warning, at.info, at.error):
        parts += [e.value for e in group]
    for m in at.metric:
        parts += [str(m.label), str(m.value), str(m.delta)]
    return " ".join(parts)


def test_recommendations_page_renders_three_picks_and_a_chart():
    at = AppTest.from_function(_rec_app, default_timeout=60).run()
    assert not at.exception
    t = _text(at)
    assert "Best for soil and climate" in t and "Highest profit" in t and "Best for your soil" in t
    assert "vs current" in t and "EXAMPLE DATA" not in t
    assert len(at.slider) == 4 and "Not a guarantee of yield or profit" in t
    assert len(at.metric) >= 15 and not any("Do not use them" in w.value for w in at.warning)


def test_moving_a_slider_reruns_without_error_and_keeps_the_guardrail():
    at = AppTest.from_function(_rec_app, default_timeout=60).run()
    at.slider(key="rec_bad").set_value(100).run()
    assert not at.exception
    at.slider(key="rec_tol").set_value(25).run()
    assert not at.exception and "Best for soil and climate" in _text(at)


def test_area_unit_acre_changes_the_money_unit_shown():
    ha = _text(AppTest.from_function(_rec_app, default_timeout=60).run())
    ac = _text(AppTest.from_function(_rec_acre_app, default_timeout=60).run())
    assert "per ha per year" in ha and "per acre per year" in ac and "per acre" not in ha


def test_stand_in_simulation_shows_the_red_example_badge_and_warning():
    at = AppTest.from_function(_rec_example_app, default_timeout=60).run()
    assert not at.exception
    t = _text(at)
    assert "EXAMPLE DATA" in t and "Do not use them for decisions" in t


def test_missing_price_shows_input_needed_not_numbers():
    at = AppTest.from_function(_rec_input_needed_app, default_timeout=60).run()
    assert not at.exception
    t = _text(at)
    assert "Input needed" in t and "Quinoa" in t and "Nothing is filled in for you" in t


def test_measure_page_ranks_questions_in_plain_words():
    at = AppTest.from_function(_measure_app, default_timeout=90).run()
    assert not at.exception
    t = _text(at)
    assert "What to measure next" in t and "upper bound" in t
    assert "Could change your answer" in t or "Probably won't change your answer" in t
    assert "organic matter" in t.lower() and "team to verify" in t


def _rec_nan_yield_app():
    import sys; sys.path.insert(0, "tests")
    import numpy as np
    import ui_fixtures as fx
    from ui import recommendations

    def sim(s, i, rotation, scenarios):
        r = fx.simulate(s, i, rotation, scenarios)
        r["yields_kg_ha"] = r["yields_kg_ha"] * np.nan          # no yield number for any crop
        return r
    recommendations.render(fx.site(), fx.inputs(), simulate=sim, scenarios=list(range(10)), crops=fx.CROPS)


def _rec_current_best_app():
    import sys; sys.path.insert(0, "tests")
    import ui_fixtures as fx
    from ui import recommendations
    recommendations.render(fx.site(), fx.inputs(plan=("maize",) * 4), simulate=fx.simulate, scenarios=list(range(10)), crops=fx.CROPS)


def test_crop_with_no_yield_number_asks_for_a_yield_like_a_missing_price():
    at = AppTest.from_function(_rec_nan_yield_app, default_timeout=60).run()
    assert not at.exception
    t = _text(at)
    assert "Input needed" in t and "your yield for Sorghum" in t and "Nothing is filled in for you" in t


def test_headline_that_is_the_current_plan_says_so():
    at = AppTest.from_function(_rec_current_best_app, default_timeout=60).run()
    assert not at.exception
    assert "already the best match" in _text(at)
