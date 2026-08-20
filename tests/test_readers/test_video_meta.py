"""Tests for track2data.readers.video_meta.extract_frame."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from track2data.readers.video_meta import extract_frame

# ── real-environment tests (no mocking) ─────────────────────────────────────
#
# This project's [dev] extras do not include `av` (only the separate [video]
# extra does -- see pyproject.toml's [project.optional-dependencies]), so in
# this environment `import av` inside extract_frame() genuinely fails and the
# function honestly exercises its own `except ImportError: return None`
# graceful-degradation branch on every call, regardless of the path given.


class TestExtractFrameAvNotInstalled:
    def test_returns_none_for_arbitrary_path(self) -> None:
        assert extract_frame(Path("anything")) is None

    def test_does_not_raise_for_arbitrary_path(self) -> None:
        extract_frame(Path("anything"))  # must not raise

    def test_returns_none_with_nondefault_frame_index(self) -> None:
        assert extract_frame(Path("anything.mp4"), frame_index=5) is None


class TestExtractFrameNonexistentPath:
    def test_returns_none_for_nonexistent_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.mp4"
        assert extract_frame(missing) is None

    def test_does_not_raise_for_nonexistent_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.mp4"
        extract_frame(missing, frame_index=3)  # must not raise


# ── deterministic ImportError branch (independent of environment) ──────────


class TestExtractFrameAvUnavailableViaSysModules:
    """Forces the `except ImportError` branch via sys.modules, so this test's
    outcome does not depend on whether `av` happens to be installed."""

    def test_returns_none_when_av_import_fails(self, tmp_path: Path) -> None:
        with patch.dict(sys.modules, {"av": None}):
            assert extract_frame(tmp_path / "video.mp4") is None


# ── bonus: simulate a successful `av` import ────────────────────────────────


def _make_fake_av(frames: list, open_side_effect: Exception | None = None) -> MagicMock:
    """Build a mock `av` module whose call chain mirrors extract_frame()'s usage:

    av.open(path) -> container (context manager)
    container.streams.video[0] -> stream
    stream.codec_context.skip_frame = "NONREF"
    container.decode(stream) -> iterable of frame-like objects
    frame.to_image().tobytes() -> bytes
    """
    fake_stream = MagicMock(name="video_stream")
    fake_container = MagicMock(name="container")
    fake_container.streams.video = [fake_stream]
    fake_container.decode.return_value = frames
    fake_container.__enter__.return_value = fake_container
    fake_container.__exit__.return_value = False

    fake_av = MagicMock(name="av")
    if open_side_effect is not None:
        fake_av.open.side_effect = open_side_effect
    else:
        fake_av.open.return_value = fake_container
    return fake_av


class TestExtractFrameAvAvailable:
    def test_returns_bytes_for_matching_frame_index(self, tmp_path: Path) -> None:
        fake_frame = MagicMock(name="frame")
        fake_frame.to_image.return_value.tobytes.return_value = b"\x01\x02\x03"
        fake_av = _make_fake_av(frames=[fake_frame])

        with patch.dict(sys.modules, {"av": fake_av}):
            result = extract_frame(tmp_path / "video.mp4", frame_index=0)

        assert result == b"\x01\x02\x03"

    def test_sets_skip_frame_to_nonref(self, tmp_path: Path) -> None:
        fake_frame = MagicMock(name="frame")
        fake_frame.to_image.return_value.tobytes.return_value = b"\x00"
        fake_av = _make_fake_av(frames=[fake_frame])

        with patch.dict(sys.modules, {"av": fake_av}):
            extract_frame(tmp_path / "video.mp4", frame_index=0)

        stream = fake_av.open.return_value.streams.video[0]
        assert stream.codec_context.skip_frame == "NONREF"

    def test_returns_none_when_frame_index_not_found(self, tmp_path: Path) -> None:
        fake_frame = MagicMock(name="frame")
        fake_av = _make_fake_av(frames=[fake_frame])  # only index 0 available

        with patch.dict(sys.modules, {"av": fake_av}):
            result = extract_frame(tmp_path / "video.mp4", frame_index=5)

        assert result is None

    def test_returns_none_when_av_open_raises(self, tmp_path: Path) -> None:
        fake_av = _make_fake_av(frames=[], open_side_effect=RuntimeError("bad file"))

        with patch.dict(sys.modules, {"av": fake_av}):
            result = extract_frame(tmp_path / "corrupt.mp4", frame_index=0)

        assert result is None
