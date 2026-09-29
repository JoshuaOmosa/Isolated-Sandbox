import pytest

from solution import LRUCache


def test_put_and_get():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert len(cache) == 1


def test_get_missing_returns_default():
    cache = LRUCache(2)
    assert cache.get("x") is None
    assert cache.get("x", default=42) == 42


def test_evicts_least_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert "a" not in cache
    assert cache.keys() == ["b", "c"]


def test_get_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert "b" not in cache and "a" in cache


def test_updating_existing_key_does_not_evict():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    assert len(cache) == 2
    assert cache.get("a") == 10
    assert cache.keys() == ["b", "a"]


def test_contains_does_not_refresh_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert "a" in cache
    cache.put("c", 3)
    assert "a" not in cache


def test_stats_track_hits_misses_evictions():
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.get("a")
    cache.get("nope")
    cache.put("b", 2)
    assert cache.stats() == {"hits": 1, "misses": 1, "evictions": 1}


def test_invalid_capacity():
    with pytest.raises(ValueError):
        LRUCache(0)
