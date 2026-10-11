"""Native sessions of one project must share a vertical axis: one water column serves them all."""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.api import Engine
from track2data.core.errors import ImportError_
from track2data.core.models import SessionRef

from .test_project_rules import _manifest, _native


def _ref(session_id: str, axis: str | None = None, **extra) -> SessionRef:
    options: dict = {"fps": 25.0, "unit": "mm", **extra}
    if axis is not None:
        options["vertical_axis"] = axis
    return SessionRef(
        session_id=session_id,
        folder=Path("/tmp") / session_id,
        sha256="",
        reader="anipose",
        reader_options=options,
    )


def _with_axis(session, axis: str):
    attrs = {"native_3d": {"vertical_axis": axis, "flip": False}}
    return session.model_copy(update={"raw_attrs": attrs})


def test_a_batch_with_two_vertical_axes_is_refused_naming_both() -> None:
    engine = Engine(_manifest([]))
    with pytest.raises(ImportError_) as caught:
        engine.check_native_refs([_ref("a", "z"), _ref("b", "y")])
    assert caught.value.code == "NATIVE_3D_AXIS_MISMATCH"
    message = str(caught.value)
    assert "'a'" in message and "'b'" in message and "'z'" in message and "'y'" in message


def test_a_file_on_another_axis_than_the_projects_is_refused() -> None:
    engine = Engine(_manifest([_ref("a", "z")]))
    with pytest.raises(ImportError_) as caught:
        engine.check_native_refs([_ref("b", "x")])
    assert caught.value.code == "NATIVE_3D_AXIS_MISMATCH"
    assert "'a'" in str(caught.value) and "'b'" in str(caught.value)


def test_the_default_axis_is_z_when_the_option_is_not_saved() -> None:
    engine = Engine(_manifest([_ref("a")]))  # no vertical_axis saved: z
    engine.check_native_refs([_ref("b", "z")])  # does not raise
    with pytest.raises(ImportError_):
        engine.check_native_refs([_ref("c", "y")])


def test_the_same_axis_with_a_different_flip_is_accepted() -> None:
    engine = Engine(_manifest([_ref("a", "z", flip=False)]))
    engine.check_native_refs([_ref("b", "z", flip=True)])


def test_a_read_session_on_another_axis_is_refused() -> None:
    engine = Engine(_manifest([_ref("a", "z")]))
    with pytest.raises(ImportError_) as caught:
        engine.check_native_import(_with_axis(_native("b"), "y"))
    assert caught.value.code == "NATIVE_3D_AXIS_MISMATCH"


def test_a_read_session_on_the_projects_axis_is_accepted() -> None:
    engine = Engine(_manifest([_ref("a", "y")]))
    engine.check_native_import(_with_axis(_native("b"), "y"))


def test_a_session_without_axis_attributes_counts_as_z() -> None:
    engine = Engine(_manifest([_ref("a", "z")]))
    engine.check_native_import(_native("b"))  # raw_attrs carries nothing: z


def test_the_refusal_says_how_to_fix_it() -> None:
    engine = Engine(_manifest([_ref("a", "z")]))
    with pytest.raises(ImportError_) as caught:
        engine.check_native_refs([_ref("b", "y")])
    assert "vertical_axis" in (caught.value.remediation or "")


def test_a_project_whose_files_already_disagree_is_refused_when_one_is_read() -> None:
    """The rule runs on every import, as the unit rule does, so an existing mixed project says
    why instead of computing a water column that means two things."""
    engine = Engine(_manifest([_ref("a", "z"), _ref("b", "y")]))
    with pytest.raises(ImportError_) as caught:
        engine.check_native_import(_native("a"))
    assert caught.value.code == "NATIVE_3D_AXIS_MISMATCH"
