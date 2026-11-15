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
