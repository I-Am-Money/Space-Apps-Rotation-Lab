# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Bounded, thread-safe caches for immutable model output arrays."""
from collections import OrderedDict
from threading import RLock

import numpy as np


def size_bytes(value):
    if isinstance(value, np.ndarray):
        return value.nbytes
    if isinstance(value, dict):
        return sum(size_bytes(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(size_bytes(v) for v in value)
    return 64


def freeze_arrays(value):
    if isinstance(value, np.ndarray):
        value.setflags(write=False)
    elif isinstance(value, dict):
        for item in value.values():
            freeze_arrays(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            freeze_arrays(item)


class ArrayCache:
    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self.bytes = 0
        self._items = OrderedDict()
        self._lock = RLock()

    def __contains__(self, key):
        with self._lock:
            return key in self._items

    def __len__(self):
        with self._lock:
            return len(self._items)

    def __getitem__(self, key):
        with self._lock:
            value, size = self._items.pop(key)
            self._items[key] = value, size
            return value

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key, value):
        freeze_arrays(value)
        size = size_bytes(value)
        with self._lock:
            if key in self._items:
                self.bytes -= self._items.pop(key)[1]
            self._items[key] = value, size
            self.bytes += size
            while self.bytes > self.max_bytes and len(self._items) > 1:
                _, (_, old_size) = self._items.popitem(last=False)
                self.bytes -= old_size

    def clear(self):
        with self._lock:
            self._items.clear()
            self.bytes = 0


# =====================================================================================================
# Build Spec v4 disk cache (Person 2). Task 1: cache by location with expiry, offline-safe, data_as_of.
#
# Two folders, same file layout (<kind>/<key>.json.gz):
#   data/precache/  committed to the repo: demo and validation sites fetched ahead of time (read-only seed)
#   data/cache/     written at run time (git-ignored)
# A cached entry is "fresh" while it is younger than its expiry (R24): weather, prices and yields 7 days;
# soil, elevation and other slow-changing data 1 year. fetch_cached() returns a fresh entry without touching
# the network, refreshes a stale one, and if the refresh fails (offline, API down) returns the stale copy
# marked stale=True instead of failing. Every entry records data_as_of (the day it was downloaded), its
# source name and URL. Nothing is ever invented: with no cache and no network it raises DataUnavailable.
# =====================================================================================================
import datetime as _dt
import gzip as _gzip
import json as _json
import os as _os
import re as _re
import tempfile as _tempfile
import io as _io
import math as _math
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parent.parent
PRECACHE_DIR = ROOT / "data" / "precache"
RUNTIME_DIR = ROOT / "data" / "cache"
EXPIRY_DAYS = {"weather": 7, "prices": 7, "yields": 7, "nass": 7,
               "soil": 365, "elevation": 365, "geo": 365, "costs": 365, "layers": 365}
DEFAULT_EXPIRY_DAYS = 7


class DataUnavailable(RuntimeError):
    """No cached copy and the source could not be reached. Callers use the documented fallback."""


def expiry_days(kind: str) -> int:
    return EXPIRY_DAYS.get(kind, DEFAULT_EXPIRY_DAYS)


def location_key(lat: float, lon: float, ndigits: int = 3) -> str:
    """Cache key for a point. 3 decimals is about 100 m, far finer than the 0.5 degree weather grid."""
    lat, lon = float(lat), float(lon)
    if not _math.isfinite(lat) or not _math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Invalid cache coordinates")
    return f"{round(lat, ndigits):.{ndigits}f}_{round(lon, ndigits):.{ndigits}f}"


def _safe(key: str) -> str:
    return _re.sub(r"[^A-Za-z0-9_.\-]", "_", str(key))


def _path(base: _Path, kind: str, key: str) -> _Path:
    return base / _safe(kind) / f"{_safe(key)}.json.gz"


def _today() -> _dt.date:
    return _dt.date.today()


def _load(path: _Path):
    try:
        with _gzip.open(path, "rt", encoding="utf-8") as f:
            doc = _json.load(f)
        return doc["payload"], doc["meta"]
    except Exception:
        return None


def age_days(meta: dict, today: _dt.date | None = None) -> int:
    return ((today or _today()) - _dt.date.fromisoformat(meta["data_as_of"])).days


def is_fresh(meta: dict, today: _dt.date | None = None) -> bool:
    return age_days(meta, today) < int(meta.get("expiry_days", DEFAULT_EXPIRY_DAYS))


def read(kind: str, key: str):
    """(payload, meta) of the newest cached copy (runtime cache or committed pre-cache), or None."""
    best = None
    for base in (RUNTIME_DIR, PRECACHE_DIR):
        got = _load(_path(base, kind, key))
        if got and (best is None or got[1]["data_as_of"] > best[1]["data_as_of"]):
            best = got
    return best


def write(kind: str, key: str, payload, source: str, url: str = "", precache: bool = False,
          data_as_of: str | None = None) -> dict:
    """Store payload (JSON-serializable). precache=True writes the committed seed folder."""
    meta = {"kind": kind, "key": key, "source": source, "url": url,
            "data_as_of": data_as_of or _today().isoformat(), "expiry_days": expiry_days(kind)}
    path = _path(PRECACHE_DIR if precache else RUNTIME_DIR, kind, key)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        previous = _load(path)
        if previous and previous == (payload, meta):
            return dict(meta, stored=True)
        fd, name = _tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        _os.close(fd)
        temporary = _Path(name)
        with temporary.open('wb') as binary:
            with _gzip.GzipFile(filename='', fileobj=binary, mode='wb', mtime=0) as compressed:
                with _io.TextIOWrapper(compressed, encoding='utf-8') as text:
                    _json.dump({'meta': meta, 'payload': payload}, text, separators=(',', ':'), allow_nan=False)
        _os.replace(temporary, path)
        return dict(meta, stored=True)
    except OSError:
        return dict(meta, stored=False)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def offline() -> bool:
    """ROTATIONLAB_OFFLINE=1 forbids every network call (tests, demos without internet)."""
    return _os.environ.get("ROTATIONLAB_OFFLINE", "").strip() in ("1", "true", "yes")


def fetch_cached(kind: str, key: str, fetcher, source: str, url: str = "", refresh: str = "auto",
                 precache: bool = False):
    """Return (payload, meta). meta has data_as_of, source, url, expiry_days, stale (bool), from_cache (bool).

    refresh: "auto"  use a fresh cached copy; refresh a stale or missing one; fall back to the stale copy
                     if the source cannot be reached.
             "never" use any cached copy whatever its age (instant demo sites); fetch only if none exists.
             "force" always fetch; fall back to the cached copy if the fetch fails.
    fetcher() must return a JSON-serializable payload, or raise.
    """
    if refresh not in ("auto", "never", "force"):
        raise ValueError("refresh must be auto, never or force")
    cached = read(kind, key)
    if cached and refresh != "force" and (refresh == "never" or is_fresh(cached[1])):
        if precache:
            write(kind, key, cached[0], cached[1]["source"], cached[1].get("url", ""), precache=True, data_as_of=cached[1]["data_as_of"])
        return cached[0], dict(cached[1], stale=not is_fresh(cached[1]), from_cache=True)
    if not offline():
        try:
            payload = fetcher()
            meta = write(kind, key, payload, source, url, precache=precache)
            return payload, dict(meta, stale=False, from_cache=False)
        except Exception as err:          # network or API failure: fall through to the stale copy
            failure = f"{type(err).__name__}: {err}"
    else:
        failure = "offline mode (ROTATIONLAB_OFFLINE)"
    if cached:
        if precache:
            write(kind, key, cached[0], cached[1]["source"], cached[1].get("url", ""), precache=True, data_as_of=cached[1]["data_as_of"])
        return cached[0], dict(cached[1], stale=True, from_cache=True, refresh_error=failure)
    raise DataUnavailable(f"{source}: no cached copy for {kind}/{key} and the source is unreachable ({failure})")
