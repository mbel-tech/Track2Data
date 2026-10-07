"""The corpus-validation script runs end to end on a synthetic corpus."""

from __future__ import annotations

import importlib.util
import json
import pickle
import sys
import types
from pathlib import Path

import pytest

from tests.conftest import _build_tiny_real_session

SCRIPT = Path(__file__).parent.parent / "scripts" / "validate_blob_diagnostics.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("validate_blob_diagnostics", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_blob_diagnostics"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_blobs(folder: Path, *, corrected_frame: int | None) -> None:
    """A blob pickle with 10 unicity frames of two 10x10 animals."""
    pkg = types.ModuleType("idtrackerai")
    pkg.__path__ = []  # type: ignore[attr-defined]
    blob_mod = types.ModuleType("idtrackerai.blob")
    lob_mod = types.ModuleType("idtrackerai.list_of_blobs")
    blob_cls = type("Blob", (), {"__module__": "idtrackerai.blob"})
    lob_cls = type("ListOfBlobs", (), {"__module__": "idtrackerai.list_of_blobs"})
    blob_mod.Blob, lob_mod.ListOfBlobs = blob_cls, lob_cls  # type: ignore[attr-defined]
    names = ("idtrackerai", "idtrackerai.blob", "idtrackerai.list_of_blobs")
    saved = {k: sys.modules.get(k) for k in names}
    sys.modules.update(zip(names, (pkg, blob_mod, lob_mod), strict=True))
    try:
        square = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
        frames = []
        for t in range(10):
            frame = []
            for ident in (1, 2):
                b = blob_cls()
                b.__dict__.update(
                    seems_like_individual=True, identity=ident, identity_certainty=0.9,
                    contour=square,
                    identity_corrected_solving_jumps=(2 if t == corrected_frame else None),
                )
                frame.append(b)
            frames.append(frame)
        lob = lob_cls()
        lob.__dict__["blobs_in_video"] = frames
        (folder / "preprocessing" / "list_of_blobs.pickle").write_bytes(pickle.dumps(lob))
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _write_fragments(folder: Path) -> None:
    def frag(i, start, end, **kw):
        return {"identifier": i, "start_frame": start, "end_frame": end,
                "is_an_individual": True, **kw}

    data = {"n_animals": 2, "fragments": [
        frag(0, 0, 10, identity=1, certainty=0.95, identity_is_fixed=True),
        frag(1, 0, 10, identity=2, certainty=0.3),
        frag(2, 0, 5),
    ]}
    (folder / "preprocessing" / "list_of_fragments.json").write_text(json.dumps(data))


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    for name, corrected in (("session_a", 4), ("session_b", None)):
        folder = root / name
        _build_tiny_real_session(folder)
        _write_fragments(folder)
        _write_blobs(folder, corrected_frame=corrected)
    return root


def test_report_covers_body_length_fragments_and_corrections(corpus: Path, tmp_path: Path) -> None:
    import pandas as pd

    script = _load_script()
    out = tmp_path / "report"
    assert script.main([str(corpus), "--allow-pickle", "--out", str(out)]) == 0

    df = pd.read_csv(out.with_suffix(".csv")).set_index("session_id")
    a = df.loc["session_a"]
    # Blob diagonal of a 100x100 square is 100*sqrt(2); the fixture's
    # session-wide body_length is 150.15.
    assert a["body_length_blob_px"] == pytest.approx(141.42, abs=0.01)
    assert a["blob_to_session_ratio_median"] == pytest.approx(141.42 / 150.15, abs=1e-3)
    assert a["corrected_attribute_present"] and a["n_corrected_frames"] == 1
    assert df.loc["session_b", "n_corrected_frames"] == 0
    # Two of three fragments carry a certainty; 10 of 25 fragment-frames are >= 0.5.
    assert a["frac_fragments_with_certainty"] == pytest.approx(2 / 3)
    assert a["frac_frames_certain_0.5"] == pytest.approx(10 / 20)
    assert a["frac_frames_certain_0.1"] == pytest.approx(20 / 20)

    text = out.with_suffix(".md").read_text()
    assert "Sessions scanned: 2" in text and "D-14 sensitivity" in text
    assert "identity_corrected_solving_jumps" in text


def test_without_allow_pickle_the_blob_columns_are_skipped(corpus: Path, tmp_path: Path) -> None:
    import pandas as pd

    script = _load_script()
    out = tmp_path / "report"
    script.main([str(corpus), "--out", str(out)])
    df = pd.read_csv(out.with_suffix(".csv"))
    # tiny_real ships trajectories.npy (a pickle) plus the csv bundle, so
    # sessions still read; only the blob-derived columns are absent.
    assert "body_length_blob_px" not in df.columns
    assert "re-run with `--allow-pickle`" in out.with_suffix(".md").read_text()


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    assert _load_script().main([str(tmp_path)]) == 2
