"""Tests for readers.idtrackerai.preprocessing (find_preprocessing_images)."""

from __future__ import annotations

from pathlib import Path

from track2data.readers.idtrackerai.preprocessing import find_preprocessing_images


def test_no_preprocessing_dir_returns_empty(tmp_path: Path) -> None:
    assert find_preprocessing_images(tmp_path) == {}


def test_empty_preprocessing_dir_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "preprocessing").mkdir()
    assert find_preprocessing_images(tmp_path) == {}


def test_finds_roi_mask(tmp_path: Path) -> None:
    preproc = tmp_path / "preprocessing"
    preproc.mkdir()
    (preproc / "ROI_mask.png").write_bytes(b"fake png")
    found = find_preprocessing_images(tmp_path)
    assert found["roi_mask"] == preproc / "ROI_mask.png"
    assert "background" not in found


def test_finds_background(tmp_path: Path) -> None:
    preproc = tmp_path / "preprocessing"
    preproc.mkdir()
    (preproc / "background.png").write_bytes(b"fake png")
    found = find_preprocessing_images(tmp_path)
    assert found["background"] == preproc / "background.png"
    assert "roi_mask" not in found


def test_finds_both(tmp_path: Path) -> None:
    preproc = tmp_path / "preprocessing"
    preproc.mkdir()
    (preproc / "ROI_mask.png").write_bytes(b"fake png")
    (preproc / "background.png").write_bytes(b"fake png")
    found = find_preprocessing_images(tmp_path)
    assert set(found.keys()) == {"roi_mask", "background"}


def test_macos_resource_fork_ignored(tmp_path: Path) -> None:
    """A ._ROI_mask.png stub (OneDrive/iCloud sync artefact) must never be
    returned as the real file -- same filter as custom_artefacts.py."""
    preproc = tmp_path / "preprocessing"
    preproc.mkdir()
    (preproc / "._ROI_mask.png").write_bytes(b"\x00\x05\x16\x07")
    found = find_preprocessing_images(tmp_path)
    assert "roi_mask" not in found
