"""Tests for the cached_infer wrapper in src/server.py.

These tests mock the inner infer() so they don't require the full graph Redis
dataset — only a reachable Redis for the cache itself (which the server already
needs anyway, and the user port-forwards from k8s for local runs).
"""
import asyncio
from unittest.mock import patch, AsyncMock

import pytest

from src import server
from src.server import cached_infer, infer_cache_key, redis_client, INFER_CACHE_PREFIX


def minimal_infer_message(curie="MONDO:0004975"):
    return {
        "message": {
            "query_graph": {
                "nodes": {
                    "n0": {"categories": ["biolink:Drug"]},
                    "n1": {"ids": [curie], "categories": ["biolink:Disease"]},
                },
                "edges": {
                    "e0": {
                        "subject": "n0",
                        "object": "n1",
                        "predicates": ["biolink:treats"],
                        "knowledge_type": "inferred",
                        "attribute_constraints": [],
                        "qualifier_constraints": [],
                    }
                },
            }
        },
        "parameters": {"pvalue_threshold": 0.00001, "max_rules": 10},
    }


def flush_key(in_message):
    try:
        redis_client.delete(infer_cache_key(in_message))
    except Exception:
        pass


def test_cache_key_is_stable_for_identical_input():
    m1 = minimal_infer_message()
    m2 = minimal_infer_message()
    assert infer_cache_key(m1) == infer_cache_key(m2)
    assert infer_cache_key(m1).startswith(INFER_CACHE_PREFIX)


def test_cache_key_changes_when_parameters_change():
    m1 = minimal_infer_message()
    m2 = minimal_infer_message()
    m2["parameters"]["pvalue_threshold"] = 0.5
    assert infer_cache_key(m1) != infer_cache_key(m2)


def test_cache_key_changes_when_curie_changes():
    m1 = minimal_infer_message("MONDO:0004975")
    m2 = minimal_infer_message("MONDO:0005148")
    assert infer_cache_key(m1) != infer_cache_key(m2)


class _FakeRedis:
    """Minimal in-memory stand-in supporting the get/setex calls cached_infer uses."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True


def test_cached_infer_miss_then_hit_uses_cache():
    """First call runs infer() and stores result; second call returns cached value
    without invoking infer() again."""
    in_message = minimal_infer_message(curie="MONDO:TESTCACHE:0001")

    fake_result = {
        "message": {
            "query_graph": in_message["message"]["query_graph"],
            "knowledge_graph": {"nodes": {"X:1": {"name": "sentinel"}}, "edges": {}},
            "results": [{"sentinel": True}],
        }
    }

    mock_infer = AsyncMock(return_value=fake_result)
    fake_redis = _FakeRedis()

    with patch.object(server, "redis_client", fake_redis), \
         patch.object(server, "infer", mock_infer):
        # First call: cache MISS → infer() runs → result stored
        r1 = asyncio.run(cached_infer(in_message))
        assert mock_infer.call_count == 1
        assert r1["message"]["results"] == [{"sentinel": True}]
        assert len(fake_redis.store) == 1, "cache should have been populated"

        # Second call: cache HIT → infer() NOT called again
        r2 = asyncio.run(cached_infer(in_message))
        assert mock_infer.call_count == 1, "infer() should not run on cache hit"
        assert r2["message"]["results"] == [{"sentinel": True}]


def test_cached_infer_disabled_skips_cache(monkeypatch):
    """When INFER_CACHE_ENABLED is False, every call runs infer()."""
    monkeypatch.setattr(server, "INFER_CACHE_ENABLED", False)

    in_message = minimal_infer_message(curie="MONDO:TESTCACHE:0002")
    fake_result = {"message": {"results": [{"x": 1}]}}
    mock_infer = AsyncMock(return_value=fake_result)

    with patch.object(server, "infer", mock_infer):
        asyncio.run(cached_infer(in_message))
        asyncio.run(cached_infer(in_message))
        assert mock_infer.call_count == 2, "cache disabled → infer runs every time"


def test_cached_infer_survives_redis_failure():
    """If Redis read/write raises, cached_infer should still return infer()'s result."""
    in_message = minimal_infer_message(curie="MONDO:TESTCACHE:0003")
    fake_result = {"message": {"results": [{"y": 2}]}}
    mock_infer = AsyncMock(return_value=fake_result)

    broken_redis = type("BrokenRedis", (), {
        "get": lambda self, k: (_ for _ in ()).throw(RuntimeError("boom")),
        "setex": lambda self, k, ttl, v: (_ for _ in ()).throw(RuntimeError("boom")),
    })()

    with patch.object(server, "redis_client", broken_redis), \
         patch.object(server, "infer", mock_infer):
        result = asyncio.run(cached_infer(in_message))
        assert result == fake_result
        assert mock_infer.call_count == 1