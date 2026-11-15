# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Build Spec v4, Person 2 task 1: disk cache with expiry, offline-safe, data_as_of."""
import datetime as dt

import pytest

from engine import cache


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "RUNTIME_DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "PRECACHE_DIR", tmp_path / "precache")
    monkeypatch.delenv("ROTATIONLAB_OFFLINE", raising=False)
    return tmp_path


def test_expiry_rules_match_spec():
    assert cache.expiry_days("weather") == 7 and cache.expiry_days("prices") == 7
    assert cache.expiry_days("soil") == 365 and cache.expiry_days("elevation") == 365


def test_fresh_entry_is_served_without_fetching(tmp_cache):
    calls = []
    fetch = lambda: calls.append(1) or {"v": 1}
    p1, m1 = cache.fetch_cached("weather", "1.000_2.000", fetch, "test source", "http://x")
    p2, m2 = cache.fetch_cached("weather", "1.000_2.000", fetch, "test source", "http://x")
    assert p1 == p2 == {"v": 1} and len(calls) == 1
    assert m1["from_cache"] is False and m2["from_cache"] is True and m2["stale"] is False
    assert m2["data_as_of"] == dt.date.today().isoformat() and m2["source"] == "test source"


def test_stale_entry_refreshes_and_falls_back_when_offline(tmp_cache):
    old = (dt.date.today() - dt.timedelta(days=8)).isoformat()
    cache.write("weather", "k", {"v": "old"}, "s", data_as_of=old)
    p, m = cache.fetch_cached("weather", "k", lambda: {"v": "new"}, "s")
    assert p == {"v": "new"} and m["stale"] is False
    cache.write("weather", "k2", {"v": "old"}, "s", data_as_of=old)

    def boom():
        raise ConnectionError("no network")
    p, m = cache.fetch_cached("weather", "k2", boom, "s")
    assert p == {"v": "old"} and m["stale"] is True and m["data_as_of"] == old and "ConnectionError" in m["refresh_error"]


def test_soil_keeps_a_year_and_weather_a_week(tmp_cache):
    d = (dt.date.today() - dt.timedelta(days=200)).isoformat()
    cache.write("soil", "k", {"v": 1}, "s", data_as_of=d)
    cache.write("weather", "k", {"v": 1}, "s", data_as_of=d)
    assert cache.is_fresh(cache.read("soil", "k")[1]) and not cache.is_fresh(cache.read("weather", "k")[1])


def test_no_cache_and_no_network_raises_instead_of_inventing(tmp_cache, monkeypatch):
    monkeypatch.setenv("ROTATIONLAB_OFFLINE", "1")
    with pytest.raises(cache.DataUnavailable):
        cache.fetch_cached("weather", "nowhere", lambda: {"v": 1}, "s")


def test_precache_seed_is_used_and_never_mode_skips_refresh(tmp_cache):
    old = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    cache.write("weather", "demo", {"v": "seed"}, "s", precache=True, data_as_of=old)
    p, m = cache.fetch_cached("weather", "demo", lambda: {"v": "new"}, "s", refresh="never")
    assert p == {"v": "seed"} and m["stale"] is True and m["data_as_of"] == old


def test_location_key_rounds():
    assert cache.location_key(42.03754, -93.46609) == "42.038_-93.466"


def test_precache_promotes_existing_runtime_entry(tmp_cache):
    cache.write('weather','promote',{'v':1},'test source')
    cache.fetch_cached('weather','promote',lambda: pytest.fail('No network for fresh data'), 'test source',precache=True)
    assert (cache.PRECACHE_DIR/'weather'/'promote.json.gz').exists()


def test_identical_seed_writes_are_byte_stable_and_nonfinite_json_is_rejected(tmp_cache):
    cache.write('soil','stable',{'v':1},'source',precache=True)
    path=cache.PRECACHE_DIR/'soil'/'stable.json.gz'
    original=path.read_bytes()
    cache.write('soil','stable',{'v':1},'source',precache=True)
    assert path.read_bytes()==original
    with pytest.raises(ValueError):
        cache.write('soil','invalid',{'v':float('nan')},'source')
