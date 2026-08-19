"""Tests for CacheStore (content-addressed Parquet cache) — TDD RED."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from track2data.cache.store import CacheStore


class TestCacheStore:
    def test_init_creates_directory(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        assert not cache_dir.exists()
        CacheStore(cache_dir)
        assert cache_dir.exists()

    def test_cache_miss_returns_none(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        assert store.get("abc123") is None

    def test_has_returns_false_on_miss(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        assert not store.has("nonexistent_key")

    def test_key_is_deterministic(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        k1 = store.key("reader", "folder_hash", "config_hash")
        k2 = store.key("reader", "folder_hash", "config_hash")
        assert k1 == k2

    def test_key_is_hex_string(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        k = store.key("reader", "folder_hash", "config_hash")
        int(k, 16)  # raises if not hex

    def test_key_is_64_chars(self, tmp_path: Path) -> None:
        """SHA-256 produces 64 hex characters."""
        store = CacheStore(tmp_path / "cache")
        k = store.key("reader", "folder_hash", "config_hash")
        assert len(k) == 64

    def test_different_inputs_different_keys(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        k1 = store.key("reader_a", "folder_hash", "config_hash")
        k2 = store.key("reader_b", "folder_hash", "config_hash")
        assert k1 != k2

    def test_put_creates_file(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        key = store.key("r", "f", "c")
        store.put(key, df)
        assert store.has(key)

    def test_roundtrip_put_get(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        key = store.key("reader", "folderabc", "confighash")
        store.put(key, df)
        loaded = store.get(key)
        assert loaded is not None
        assert list(loaded.columns) == ["a", "b"]
        assert len(loaded) == 3
        assert list(loaded["a"]) == [1, 2, 3]

    def test_roundtrip_float_values(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        df = pd.DataFrame({"x": [1.5, 2.5, float("nan")]})
        key = store.key("r", "f", "c")
        store.put(key, df)
        loaded = store.get(key)
        assert loaded is not None
        assert loaded["x"].iloc[0] == pytest.approx(1.5)

    def test_clear_deletes_entries(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        df = pd.DataFrame({"x": [1]})
        key = "test_key_abc"
        store.put(key, df)
        n = store.clear()
        assert n >= 1
        assert not store.has(key)

    def test_clear_returns_count(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        df = pd.DataFrame({"x": [1]})
        store.put("key1", df)
        store.put("key2", df)
        n = store.clear()
        assert n >= 2

    def test_clear_empty_cache_returns_zero(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "cache")
        n = store.clear()
        assert n == 0

    def test_cache_persists_across_instances(self, tmp_path: Path) -> None:
        """A new CacheStore pointing to same dir can read old data."""
        cache_dir = tmp_path / "cache"
        store1 = CacheStore(cache_dir)
        df = pd.DataFrame({"val": [42]})
        key = store1.key("r", "f", "c")
        store1.put(key, df)

        store2 = CacheStore(cache_dir)
        loaded = store2.get(key)
        assert loaded is not None
        assert loaded["val"].iloc[0] == 42

    def test_sharded_subdirectory_structure(self, tmp_path: Path) -> None:
        """Files are stored in a 2-char sharded subdirectory."""
        store = CacheStore(tmp_path / "cache")
        df = pd.DataFrame({"z": [1]})
        key = store.key("r", "f", "c")
        store.put(key, df)
        # The shard directory should exist
        shard_dir = tmp_path / "cache" / key[:2]
        assert shard_dir.is_dir()
