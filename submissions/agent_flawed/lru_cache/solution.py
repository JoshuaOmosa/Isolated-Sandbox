class LRUCache:
    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._data = {}  # dicts keep insertion order
        self._hits = self._misses = self._evictions = 0

    def get(self, key, default=None):
        if key in self._data:
            self._hits += 1  # BUG: does not refresh recency
            return self._data[key]
        self._misses += 1
        return default

    def put(self, key, value):
        self._data[key] = value  # BUG: updating an existing key keeps its old position
        if len(self._data) > self.capacity:
            oldest = next(iter(self._data))
            del self._data[oldest]
            self._evictions += 1

    def __len__(self):
        return len(self._data)

    def __contains__(self, key):
        return key in self._data

    def keys(self):
        return list(self._data)

    def stats(self):
        return {"hits": self._hits, "misses": self._misses, "evictions": self._evictions}
