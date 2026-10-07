"""scripts/inspect_idtrackerai_output.py: describe an idtracker.ai folder safely."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "inspect_idtrackerai_output", ROOT / "scripts" / "inspect_idtrackerai_output.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["inspect_idtrackerai_output"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "trajectories").mkdir()
    arr = np.array([[1.0, np.nan], [2.0, 3.0]])
    np.save(tmp_path / "plain.npy", arr)
    np.save(tmp_path / "trajectories" / "t.npy", {"trajectories": arr, "frames_per_second": 25})
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    return tmp_path


def test_tree_lists_every_file_with_size(mod, folder) -> None:
    text = "\n".join(mod.file_tree(folder))
    assert "plain.npy" in text and "t.npy" in text and "notes.txt" in text


def test_plain_array_described_without_pickle(mod, folder) -> None:
    text = "\n".join(mod.describe_npy(folder / "plain.npy", allow_pickle=False))
    assert "shape=(2, 2)" in text and "float64" in text and "nan=1" in text


def test_object_array_is_not_loaded_without_flag(mod, folder) -> None:
    text = "\n".join(mod.describe_npy(folder / "trajectories" / "t.npy", allow_pickle=False))
    assert "allow-pickle" in text
    assert "frames_per_second" not in text


def test_object_array_described_with_flag(mod, folder) -> None:
    text = "\n".join(mod.describe_npy(folder / "trajectories" / "t.npy", allow_pickle=True))
    assert "dict" in text and "frames_per_second" in text and "trajectories" in text


def test_pickle_is_never_executed_without_flag(mod, tmp_path) -> None:
    marker = tmp_path / "pwned"

    class Evil:
        def __reduce__(self):
            return (marker.write_text, ("x",))

    bad = tmp_path / "evil.npy"
    np.save(bad, np.array([Evil()], dtype=object), allow_pickle=True)
    mod.describe_npy(bad, allow_pickle=False)
    assert not marker.exists()


def test_main_prints_versions_and_tree(mod, folder, capsys) -> None:
    assert mod.main([str(folder)]) == 0
    out = capsys.readouterr().out
    assert "numpy" in out and "plain.npy" in out


def test_main_rejects_missing_folder(mod, tmp_path, capsys) -> None:
    assert mod.main([str(tmp_path / "nope")]) == 2


def test_unreadable_file_is_reported_not_raised(mod, tmp_path) -> None:
    bad = tmp_path / "broken.npy"
    bad.write_bytes(b"not an npy file")
    assert any("cannot read" in line for line in mod.describe_npy(bad, allow_pickle=True))

