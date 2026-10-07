"""Content-addressed Parquet cache for preprocessed session data."""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class CacheStore:
    """Content-addressed Parquet cache.

    Key = SHA-256(reader_name + session_folder_hash + preprocess_config_hash)

    Directory layout::

        cache_dir/
            {key[:2]}/
                {key}.parquet
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── key computation ────────────────────────────────────────────────────────

    def key(self, reader_name: str, folder_hash: str, config_hash: str) -> str:
        """Compute the cache key.

        Parameters
        ----------
        reader_name:
            Name of the reader used to load the session.
        folder_hash:
            SHA-256 (or similar) digest of the session folder contents.
        config_hash:
            SHA-256 (or similar) digest of the preprocessing configuration.

        Returns
        -------
        str
            64-character lowercase hex string (SHA-256).
        """
        raw = (reader_name + folder_hash + config_hash).encode()
        return hashlib.sha256(raw).hexdigest()

    # ── path helper ────────────────────────────────────────────────────────────

    def _path(self, key: str) -> Path:
        return self._dir / key[:2] / f"{key}.parquet"

    # ── public interface ───────────────────────────────────────────────────────

    def has(self, key: str) -> bool:
        """Check if *key* exists without loading the data.

        Parameters
        ----------
        key:
            Cache key (typically from :meth:`key`).

        Returns
        -------
        bool
        """
        return self._path(key).exists()

    def get(self, key: str) -> pd.DataFrame | None:
        """Return the cached :class:`~pandas.DataFrame` or ``None`` on miss.

        Parameters
        ----------
        key:
            Cache key.

        Returns
        -------
        pd.DataFrame | None
        """
        path = self._path(key)
        if not path.exists():
            return None
        return pd.read_parquet(path, engine="pyarrow")

    def put(self, key: str, df: pd.DataFrame) -> None:
        """Write *df* to the cache.

        Parameters
        ----------
        key:
            Cache key.
        df:
            DataFrame to persist.
        """
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, engine="pyarrow", index=False)

    # ── object entries (preprocessed sessions) ─────────────────────────────────

    def _object_path(self, key: str) -> Path:
        return self._dir / key[:2] / f"{key}.pkl"

    def has_object(self, key: str) -> bool:
        return self._object_path(key).exists()

    def get_object(self, key: str) -> Any | None:
        """Return the pickled object stored under *key*, or ``None``.

        A truncated or otherwise unreadable entry is treated as a miss and
        deleted, so a crash mid-write can never wedge later runs. The cache
        directory is written by this process's own ``put_object`` and lives
        in the user's project folder; it is not a trust boundary.
        """
        path = self._object_path(key)
        if not path.exists():
            return None
        try:
            with path.open("rb") as fh:
                return pickle.load(fh)
        except Exception:
            logger.warning("Discarding unreadable cache entry %s", path.name)
            path.unlink(missing_ok=True)
            return None

    def put_object(self, key: str, obj: Any) -> None:
        """Persist *obj* under *key* atomically (write temp, then replace)."""
        path = self._object_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        with tmp.open("wb") as fh:
            pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)

    def clear(self) -> int:
        """Delete all cached Parquet and object files.

        Returns
        -------
        int
            Number of files deleted.
        """
        count = 0
        for pattern in ("*.parquet", "*.pkl"):
            for entry in self._dir.rglob(pattern):
                entry.unlink()
                count += 1
        return count
