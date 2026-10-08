"""A session that carries a skeleton must survive the preprocessed-session cache.

The cache pickles whole sessions. A new Session field is invisible to entries written before it
existed (they unpickle without the attribute), so the cache schema is bumped when one is added:
old entries then simply miss and are rebuilt, instead of failing on first use.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from track2data.api import Engine
from track2data.cache.store import CacheStore
from track2data.readers.assemble import assemble_session, build_keypoints, reduce_keypoints


def test_a_session_with_a_skeleton_round_trips_through_the_cache(tmp_path: Path) -> None:
    xy = np.random.default_rng(0).uniform(0, 100, size=(20, 2, 3, 2))
    reduction = reduce_keypoints(xy, ["a", "b", "c"], keypoint="b")
    keypoints = build_keypoints(xy, ["a", "b", "c"], None, [(0, 1)], reduction.selection)
    session = assemble_session(
        session_id="s",
        folder=tmp_path,
        reader="toy",
        fps=30.0,
        width_px=100,
        height_px=100,
        raw_xy=reduction.raw_xy,
        has_stable_identities=True,
        keypoints=keypoints,
    )
    store = CacheStore(tmp_path / "cache")
    store.put_object("k", session)

    back = store.get_object("k")

    assert back.keypoints is not None
    assert back.keypoints.names == ["a", "b", "c"] and back.keypoints.edges == [(0, 1)]
    assert back.keypoints.selection.keypoint == "b"
    assert np.array_equal(back.keypoints.xy, keypoints.xy)


def test_the_cache_schema_was_bumped_when_session_gained_keypoints() -> None:
    # Entries written at schema 1 have no `keypoints` attribute; a new schema makes them miss.
    assert Engine._CACHE_SCHEMA >= 2
