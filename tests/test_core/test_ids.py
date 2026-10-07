"""Session ids: one derivation, Windows-safe, unique, and unchanged for existing folders."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from track2data.core.ids import default_session_id, sanitise_session_id, uniquify


class TestDefaultSessionId:
    def test_a_directory_keeps_its_name_verbatim(self, tmp_path: Path) -> None:
        # Existing projects join metadata on this exact string; it must never change.
        for name in ["session_trial10_Segment1", "fish 3", "run.v2", "été", "a" * 200]:
            folder = tmp_path / name
            folder.mkdir()
            assert default_session_id(folder) == name

    def test_a_file_is_named_after_its_stem(self, tmp_path: Path) -> None:
        file = tmp_path / "trial01DLC_resnet50.h5"
        file.write_bytes(b"x")
        assert default_session_id(file) == "trial01DLC_resnet50"

    def test_a_file_stem_is_sanitised(self) -> None:
        # "?" and "*" are not legal file-name characters on Windows, so use a Path object
        # that never touches the file system. (No colon: "a:" would parse as a drive.)
        assert default_session_id(Path("a?b*c.csv"), is_file=True) == "a_b_c"

    def test_a_path_that_does_not_exist_keeps_its_name_like_a_directory(self) -> None:
        # Tests and probes build Session objects for folders that are not on disk; their id
        # has always been ``folder.name`` and must not lose a ".v2" suffix.
        assert default_session_id(Path("run.v2")) == "run.v2"
        assert default_session_id(Path("a?b")) == "a?b"


class TestSanitise:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ok name", "ok name"),
            ("a/b\\c", "a_b_c"),
            ('a:b*c?"d<e>f|g', "a_b_c__d_e_f_g"),
            ("trailing. ", "trailing"),
            ("CON", "CON_"),
            ("nul", "nul_"),
            ("com1", "com1_"),
            ("", "session"),
            ("...", "session"),
            ("a\x00b", "a_b"),
        ],
    )
    def test_known_cases(self, raw: str, expected: str) -> None:
        assert sanitise_session_id(raw) == expected

    def test_is_truncated(self) -> None:
        assert len(sanitise_session_id("x" * 500, max_len=120)) == 120

    @given(st.text())
    def test_never_empty_and_has_no_separators(self, raw: str) -> None:
        out = sanitise_session_id(raw)
        assert out
        assert not set(out) & set('/\\:*?"<>|\x00')

    @given(st.text())
    def test_is_idempotent(self, raw: str) -> None:
        once = sanitise_session_id(raw)
        assert sanitise_session_id(once) == once


class TestUniquify:
    def test_already_unique_is_unchanged(self) -> None:
        assert uniquify(["a", "b", "c"]) == ["a", "b", "c"]

    def test_duplicates_get_a_numbered_suffix_in_order(self) -> None:
        assert uniquify(["a", "a", "b", "a"]) == ["a", "a__2", "b", "a__3"]

    def test_taken_ids_are_respected(self) -> None:
        assert uniquify(["a", "b"], taken={"a"}) == ["a__2", "b"]

    def test_suffixes_do_not_collide_with_real_names(self) -> None:
        assert uniquify(["a", "a", "a__2"]) == ["a", "a__3", "a__2"]

    @given(st.lists(st.text(min_size=1, max_size=6), max_size=30))
    def test_result_is_unique_and_same_length(self, ids: list[str]) -> None:
        out = uniquify(ids)
        assert len(out) == len(ids)
        assert len(set(out)) == len(out)


class TestDerivationsAgree:
    """Pins the three existing derivations to the helper before they are routed through it."""

    def test_both_idtracker_readers_use_the_helper(
        self, tiny_real_session: Path, tiny_v5_session: Path
    ) -> None:
        # The classes are called directly: auto-detection claims the v5 fixture with the
        # unified reader and fails with IDT_FORMAT_AMBIGUOUS (fixed by the scan work), and
        # this test is about the id, not about detection.
        from track2data.readers import IDTrackerAiReader, IDTrackerAiV5Reader

        real = IDTrackerAiReader().read(tiny_real_session, allow_pickle=True)
        v5 = IDTrackerAiV5Reader().read(tiny_v5_session, allow_pickle=True)
        assert real.session_id == default_session_id(tiny_real_session)
        assert v5.session_id == default_session_id(tiny_v5_session)

    def test_the_project_store_uses_the_helper(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        pytest.importorskip("PySide6")
        from ui.store.project_store import ProjectStore

        store = ProjectStore()
        store.new_project("p", tmp_path)
        store.add_session(tiny_real_session)
        assert store.manifest is not None
        assert [s.session_id for s in store.manifest.sessions] == [
            default_session_id(tiny_real_session)
        ]


class TestSessionRefGuard:
    @pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b", "a\x00b"])
    def test_path_hostile_ids_are_rejected(self, bad: str, tmp_path: Path) -> None:
        from pydantic import ValidationError

        from track2data.core.models import SessionRef

        with pytest.raises(ValidationError):
            SessionRef(session_id=bad, folder=tmp_path, sha256="")

    def test_odd_but_safe_ids_still_load(self, tmp_path: Path) -> None:
        from track2data.core.models import SessionRef

        assert SessionRef(session_id="fish 3 (v2)", folder=tmp_path, sha256="").session_id
