"""Reference solution: LRU cache with hit/miss/eviction statistics."""
from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._data = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key, default=None):
        if key in self._data:
            self._data.move_to_end(key)
            self._hits += 1
            return self._data[key]
        self._misses += 1
        return default

    def put(self, key, value):
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)
            self._evictions += 1

    def __len__(self):
        return len(self._data)

    def __contains__(self, key):
        return key in self._data

    def keys(self):
        return list(self._data.keys())

    def stats(self):
        return {"hits": self._hits, "misses": self._misses, "evictions": self._evictions}
