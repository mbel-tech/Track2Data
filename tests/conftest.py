"""
Shared pytest fixtures.

The `tiny_v5_session` fixture builds a minimal synthetic idtracker.ai v5
session folder in a temporary directory.  All numeric values are chosen to
give exact, predictable results so tests can assert specific numbers.

Synthetic session spec
───────────────────────
  N_FRAMES  = 100
  N_ANIMALS = 4
  FPS       = 25.0
  WIDTH     = 1920  (pixels)
  HEIGHT    = 1080  (pixels)

Trajectories (x, y in pixels):
  Animal 0: x = 100 + frame*5,  y = 200.0          -- NaN gap at frames 20-24
  Animal 1: x = 300.0,          y = 100 + frame*4
  Animal 2: circular — x = 960 + 100*cos(frame*0.1), y = 540 + 100*sin(frame*0.1)
  Animal 3: x = 800.0,          y = 600.0           — static

trajectories_wo_gaps.npy is identical but with the NaN gap linearly filled:
  frames 20-24, animal 0:
    anchor A (frame 19): x=195, y=200
    anchor B (frame 25): x=225, y=200
    x[20]=200, x[21]=205, x[22]=210, x[23]=215, x[24]=220  (y stays 200)

Body lengths are NOT stored in tiny_v5 (body_length_px = None expected).

The `tiny_real_session` fixture mirrors a real idtracker.ai 6.0.13 session
folder at miniature scale (10 frames, 2 animals).  It matches the exact
layout observed in the 70-session corpus and the official 6.0.14 docs.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

# ── Constants shared across fixture and tests ──────────────────────────────────

TINY_V5_N_FRAMES = 100
TINY_V5_N_ANIMALS = 4
TINY_V5_FPS = 25.0
TINY_V5_WIDTH = 1920
TINY_V5_HEIGHT = 1080

# Exact frame-0 positions (used in multiple tests)
TINY_V5_FRAME0 = np.array([
    [100.0, 200.0],   # animal 0
    [300.0, 100.0],   # animal 1
    [960.0 + 100.0 * np.cos(0.0), 540.0 + 100.0 * np.sin(0.0)],  # animal 2 → [1060, 540]
    [800.0, 600.0],   # animal 3
], dtype=np.float64)

# Gap frames for animal 0 in the "with_gaps" variant
TINY_V5_GAP_FRAMES = list(range(20, 25))


def _build_raw_xy() -> np.ndarray:
    """Return (100, 4, 2) float64 trajectory array with NaN gap for animal 0."""
    xy = np.zeros((TINY_V5_N_FRAMES, TINY_V5_N_ANIMALS, 2), dtype=np.float64)
    frames = np.arange(TINY_V5_N_FRAMES, dtype=np.float64)

    xy[:, 0, 0] = 100.0 + frames * 5.0
    xy[:, 0, 1] = 200.0
    xy[20:25, 0, :] = np.nan

    xy[:, 1, 0] = 300.0
    xy[:, 1, 1] = 100.0 + frames * 4.0

    xy[:, 2, 0] = 960.0 + 100.0 * np.cos(frames * 0.1)
    xy[:, 2, 1] = 540.0 + 100.0 * np.sin(frames * 0.1)

    xy[:, 3, 0] = 800.0
    xy[:, 3, 1] = 600.0
    return xy


def _build_wo_gaps_xy() -> np.ndarray:
    """Same as raw but with NaN gap filled by linear interpolation."""
    xy = _build_raw_xy().copy()
    # anchor A: frame 19 → x=195; anchor B: frame 25 → x=225; 6-frame span
    for i, f in enumerate(range(20, 25), start=1):
        xy[f, 0, 0] = 195.0 + (225.0 - 195.0) / 6.0 * i
        xy[f, 0, 1] = 200.0
    return xy


def _build_video_object() -> dict:
    """Minimal dict that mimics a pickled VideoObject."""
    return {
        "fps": TINY_V5_FPS,
        "frame_number": TINY_V5_N_FRAMES,
        "height": TINY_V5_HEIGHT,
        "width": TINY_V5_WIDTH,
        "paths_to_video_files": ["dummy_video.mp4"],
    }


@pytest.fixture(scope="session")
def tiny_v5_session(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Build a temporary idtracker.ai v5 session directory with known content.
    Scope=session so it is created once per test run.
    """
    base = tmp_path_factory.mktemp("tiny_v5")
    traj_dir = base / "trajectories"
    traj_dir.mkdir()

    raw_xy = _build_raw_xy()
    wo_xy = _build_wo_gaps_xy()
    np.save(traj_dir / "trajectories.npy", raw_xy)
    np.save(traj_dir / "trajectories_wo_gaps.npy", wo_xy)

    video_obj = _build_video_object()
    np.save(base / "video_object.npy", video_obj)

    session_meta = {
        "session_name": base.name,
        "number_of_animals": TINY_V5_N_ANIMALS,
        "frames_per_second": TINY_V5_FPS,
        "video_height": TINY_V5_HEIGHT,
        "video_width": TINY_V5_WIDTH,
        "status": "finished",
    }
    (base / "session_progress.json").write_text(json.dumps(session_meta), encoding="utf-8")

    return base


@pytest.fixture()
def tiny_v5_no_wo_gaps(tmp_path: Path) -> Path:
    """Session folder without trajectories_wo_gaps.npy (tests fallback path)."""
    traj_dir = tmp_path / "trajectories"
    traj_dir.mkdir()
    np.save(traj_dir / "trajectories.npy", _build_raw_xy())
    np.save(tmp_path / "video_object.npy", _build_video_object())
    return tmp_path


@pytest.fixture()
def tiny_v5_transposed(tmp_path: Path) -> Path:
    """Session folder where trajectory has shape (n_animals, n_frames, 2) instead of canonical."""
    traj_dir = tmp_path / "trajectories"
    traj_dir.mkdir()
    canonical = _build_wo_gaps_xy()         # (100, 4, 2)
    transposed = canonical.transpose(1, 0, 2)  # (4, 100, 2)
    np.save(traj_dir / "trajectories_wo_gaps.npy", transposed)
    np.save(tmp_path / "video_object.npy", _build_video_object())
    return tmp_path


@pytest.fixture()
def empty_folder(tmp_path: Path) -> Path:
    return tmp_path


# ── tiny_real fixture (idtracker.ai 6.0.13 layout) ────────────────────────────

TINY_REAL_N_FRAMES = 10
TINY_REAL_N_ANIMALS = 2
TINY_REAL_FPS = 25.0
TINY_REAL_WIDTH = 1920
TINY_REAL_HEIGHT = 1080
TINY_REAL_VERSION = "6.0.13"
TINY_REAL_INCONSISTENT_FRAMES = {0, 5, 9}


def _make_minimal_png() -> bytes:
    """Build a 2x2 white grayscale PNG from scratch (no Pillow dependency)."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    ihdr_data = struct.pack(">IIBBBBB", 2, 2, 8, 0, 0, 0, 0)  # 2x2, 8-bit grayscale
    scanlines = b"\x00\xff\xff\x00\xff\xff"  # filter=none, 2 white px/row x 2 rows
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr_data)
        + _chunk(b"IDAT", zlib.compress(scanlines))
        + _chunk(b"IEND", b"")
    )


def _build_tiny_real_traj_dict() -> dict:
    """Pickled trajectory dict matching the 17 official idtracker.ai keys.

    Intentionally ships id_probabilities as (n_frames, n_animals, 1) to match
    the real-data shape deviation documented in the format analysis.
    """
    n_frames, n_animals = TINY_REAL_N_FRAMES, TINY_REAL_N_ANIMALS
    frames = np.arange(n_frames, dtype=np.float64)
    xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)
    xy[:, 0, 0] = 100.0 + frames * 5.0
    xy[:, 0, 1] = 200.0
    xy[:, 1, 0] = 300.0
    xy[:, 1, 1] = 100.0 + frames * 3.0
    return {
        "trajectories": xy,
        "id_probabilities": np.ones((n_frames, n_animals, 1), dtype=np.float64) * 0.9,
        "version": TINY_REAL_VERSION,
        "height": TINY_REAL_HEIGHT,
        "width": TINY_REAL_WIDTH,
        "video_paths": ["/Volumes/Expansion/tiny_real.mp4"],
        "frames_per_second": TINY_REAL_FPS,
        "body_length": 150.15,
        "estimated_accuracy": 0.90,
        "fraction_identified": 0.822,
        "areas": {
            "mean": np.array([150.0, 160.0]),
            "median": np.array([149.0, 158.0]),
            "std": np.array([2.0, 3.0]),
        },
        "setup_points": {},
        "identities_labels": ["1", "2"],
        "identities_groups": [],
        "length_unit": None,
        "silhouette_score": 0.781,
        "fragment_connectivity": 1.34,
    }


def _build_tiny_real_session(base: Path) -> None:
    """Populate *base* with the full tiny_real session layout."""
    n_frames, n_animals = TINY_REAL_N_FRAMES, TINY_REAL_N_ANIMALS
    session_name = base.name

    # ── trajectories/ ────────────────────────────────────────────────────────
    traj_dir = base / "trajectories"
    traj_dir.mkdir(parents=True)
    traj_dict = _build_tiny_real_traj_dict()
    np.save(traj_dir / "trajectories.npy", traj_dict, allow_pickle=True)

    # CSV bundle
    csv_dir = traj_dir / "trajectories_csv"
    csv_dir.mkdir()

    xy = traj_dict["trajectories"]
    frames = list(range(n_frames))

    # trajectories.csv: frame, x_1, y_1, x_2, y_2
    traj_rows = [["frame", "x_1", "y_1", "x_2", "y_2"]]
    for f in frames:
        traj_rows.append([f, xy[f, 0, 0], xy[f, 0, 1], xy[f, 1, 0], xy[f, 1, 1]])
    (csv_dir / "trajectories.csv").write_text(
        "\n".join(",".join(str(v) for v in row) for row in traj_rows), encoding="utf-8"
    )

    # id_probabilities.csv: frame, prob_1, prob_2
    prob = traj_dict["id_probabilities"][:, :, 0]  # (N, M)
    prob_rows = [["frame", "prob_1", "prob_2"]]
    for f in frames:
        prob_rows.append([f, prob[f, 0], prob[f, 1]])
    (csv_dir / "id_probabilities.csv").write_text(
        "\n".join(",".join(str(v) for v in row) for row in prob_rows), encoding="utf-8"
    )

    # areas.csv: frame, area_1, area_2  (per-frame blob areas — synthetic constant)
    area_rows = [["frame", "area_1", "area_2"]]
    for f in frames:
        area_rows.append([f, 3200.0, 3450.0])
    (csv_dir / "areas.csv").write_text(
        "\n".join(",".join(str(v) for v in row) for row in area_rows), encoding="utf-8"
    )

    # attributes.json — subset of trajectory dict, uses strict JSON (no Infinity here)
    attributes = {
        "version": TINY_REAL_VERSION,
        "height": TINY_REAL_HEIGHT,
        "width": TINY_REAL_WIDTH,
        "frames_per_second": TINY_REAL_FPS,
        "body_length": 150.15,
        "estimated_accuracy": 0.90,
        "fraction_identified": 0.822,
        "silhouette_score": 0.781,
        "fragment_connectivity": 1.34,
        "identities_labels": ["1", "2"],
        "identities_groups": [],
        "length_unit": None,
        "setup_points": {},
        "video_paths": ["/Volumes/Expansion/tiny_real.mp4"],
    }
    (csv_dir / "attributes.json").write_text(json.dumps(attributes), encoding="utf-8")

    # *_bboxes.csv — per-(frame, identity) bounding-box body length
    bbox_rows = [
        "session_id,frame,identity,body_length_px,body_length_cm,"
        "is_individual,is_crossing,identity_certainty,area_px"
    ]
    for f in frames:
        for ident in [1, 2]:
            bl_px = 148.0 + ident * 2.0 + f * 0.1
            bbox_rows.append(
                f"{session_name},{f},{ident},{bl_px:.2f},,True,False,0.9,3200"
            )
    (csv_dir / f"{session_name}_bboxes.csv").write_text(
        "\n".join(bbox_rows), encoding="utf-8"
    )

    # *_bboxes_summary.json
    bbox_summary = {
        "session_id": session_name,
        "status": "ok",
        "reason": "",
        "n_frames_in_blobs": n_frames,
        "n_rows_written": n_frames * n_animals,
        "identity_stats": {"1": {"median_bl_px": 150.0}, "2": {"median_bl_px": 162.0}},
        "exclusion_counts": {},
    }
    (csv_dir / f"{session_name}_bboxes_summary.json").write_text(
        json.dumps(bbox_summary), encoding="utf-8"
    )

    # ── session.json (Infinity literal — intentionally non-strict JSON) ───────
    session_json_text = (
        '{\n'
        f'  "version": "{TINY_REAL_VERSION}",\n'
        f'  "number_of_animals": {n_animals},\n'
        f'  "frames_per_second": {TINY_REAL_FPS},\n'
        f'  "number_of_frames": {n_frames},\n'
        f'  "width": {TINY_REAL_WIDTH},\n'
        f'  "height": {TINY_REAL_HEIGHT},\n'
        '  "name": "' + session_name + '",\n'
        '  "area_ths": [100.0, Infinity],\n'
        '  "intensity_ths": [10, 128],\n'
        '  "tracking_intervals": [[0, 9]],\n'
        '  "roi_list": ["+ Polygon [(10, 10), (100, 10), (100, 100), (10, 100)]"],\n'
        '  "estimated_accuracy": 0.90,\n'
        '  "fraction_identified": 0.822,\n'
        '  "silhouette_score": 0.781,\n'
        '  "fragment_connectivity": 1.34,\n'
        '  "identities_labels": ["1", "2"],\n'
        '  "identities_groups": [],\n'
        '  "identities_colors": ["#e41a1c", "#377eb8"],\n'
        '  "last_validated": "2024-01-15T10:30:00",\n'
        '  "data_policy": "trajectories_and_images",\n'
        '  "trajectories_formats": ["npy", "csv"],\n'
        '  "timers": [{"name": "tracking", "start_time": 0.0, "finish_time": 12.5}],\n'
        '  "video_paths": ["/Volumes/Expansion/tiny_real.mp4"]\n'
        '}'
    )
    (base / "session.json").write_text(session_json_text, encoding="utf-8")

    # ── idtrackerai.log ───────────────────────────────────────────────────────
    log_text = (
        "2024-01-15 10:17:32 INFO  [tracking] Starting session tracking\n"
        "2024-01-15 10:17:33 INFO  [preprocessing] ROI mask applied\n"
        "2024-01-15 10:17:45 INFO  [tracking] Tracking complete in 12.5s\n"
        "2024-01-15 10:30:00 INFO  [validation] Session validated successfully\n"
        "2024-01-15 10:30:00 INFO  [done] Status: Success\n"
    )
    (base / "idtrackerai.log").write_text(log_text, encoding="utf-8")

    # ── inconsistent_frames.csv ───────────────────────────────────────────────
    (base / "inconsistent_frames.csv").write_text(
        "\n".join(str(f) for f in sorted(TINY_REAL_INCONSISTENT_FRAMES)),
        encoding="utf-8",
    )

    # ── preprocessing/ ────────────────────────────────────────────────────────
    preproc_dir = base / "preprocessing"
    preproc_dir.mkdir()
    png_bytes = _make_minimal_png()
    (preproc_dir / "ROI_mask.png").write_bytes(png_bytes)
    (preproc_dir / "background.png").write_bytes(png_bytes)
    (preproc_dir / "list_of_fragments.json").write_text("[]", encoding="utf-8")
    (preproc_dir / "list_of_global_fragments.json").write_text("[]", encoding="utf-8")

    # ── accumulation/ (placeholder) ──────────────────────────────────────────
    acc_dir = base / "accumulation"
    acc_dir.mkdir()
    (acc_dir / "model_params.json").write_text("{}", encoding="utf-8")

    # ── macOS resource-fork noise ─────────────────────────────────────────────
    # A real OneDrive-synced session will have ._* files at every level.
    (base / "._session.json").write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00")
    (traj_dir / "._trajectories.npy").write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00")


@pytest.fixture(scope="session")
def tiny_real_session(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Build a temporary idtracker.ai 6.0.13 session directory that mirrors
    the layout observed in the real 70-session corpus.
    Scope=session so it is created once per test run.
    """
    base = tmp_path_factory.mktemp("tiny_real")
    _build_tiny_real_session(base)
    return base
