"""
Tests for ui/metadata_screen.py (issue #39) -- loading a metadata CSV
must persist a MetadataSource on the store, not just update local
widget state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt


def _make_store(tmp_path: Path):
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    return store


# ── field row labels ─────────────────────────────────────────────────────────


def test_mapping_row_labels_are_pretty_not_raw_field_names(qtbot) -> None:
    """The mapping form's row labels come from _CANONICAL_FIELDS
    (snake_case dict keys like "session_id", "trial_id") -- these must
    never appear verbatim as on-screen text, and "id"-suffixed fields
    need an explicit override since str.title() alone would render
    "Session Id" / "Trial Id", not the correct "...ID"."""
    from ui.metadata_screen import MetadataScreen

    screen = MetadataScreen()
    qtbot.addWidget(screen)

    labels = [screen._mapping_form.itemAt(i).widget().text() for i in range(0, 8, 2)]
    assert "session_id" not in labels
    assert "trial_id" not in labels
    assert "Session ID:" in labels
    assert "Trial ID:" in labels


# ── _load_csv(): persisting MetadataSource ──────────────────────────────────


def test_load_csv_persists_a_metadata_source_on_the_store(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from track2data.core.hashing import file_sha256
    from ui.metadata_screen import MetadataScreen

    csv_path = tmp_path / "trial_metadata.csv"
    csv_path.write_text("session_id,treatment\nsess_01,control\n", encoding="utf-8")

    monkeypatch.setattr(
        "ui.metadata_screen.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(csv_path), "CSV files (*.csv)")),
    )

    store = _make_store(tmp_path)
    screen = MetadataScreen(store)

    screen._load_csv()

    source = store.manifest.metadata_source
    assert source is not None
    assert source.path == csv_path
    assert source.sha256 == file_sha256(csv_path)


def test_load_csv_with_no_store_does_not_raise(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MetadataScreen() with no store is a valid construction (used by
    test_app_smoke.py's blanket widget-instantiation check) -- _load_csv
    must degrade gracefully rather than assume self._store exists."""
    from ui.metadata_screen import MetadataScreen

    csv_path = tmp_path / "trial_metadata.csv"
    csv_path.write_text("session_id,treatment\nsess_01,control\n", encoding="utf-8")

    monkeypatch.setattr(
        "ui.metadata_screen.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(csv_path), "CSV files (*.csv)")),
    )

    screen = MetadataScreen()
    screen._load_csv()  # must not raise


def test_skip_metadata_still_clears_any_previously_loaded_source(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui.metadata_screen import MetadataScreen

    csv_path = tmp_path / "trial_metadata.csv"
    csv_path.write_text("session_id,treatment\nsess_01,control\n", encoding="utf-8")
    monkeypatch.setattr(
        "ui.metadata_screen.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(csv_path), "CSV files (*.csv)")),
    )

    store = _make_store(tmp_path)
    screen = MetadataScreen(store)
    screen._load_csv()
    assert store.manifest.metadata_source is not None

    screen._skip_metadata()
    assert store.manifest.metadata_source is None


def test_mapping_change_autocommits_without_apply_button(qtbot, tmp_path) -> None:
    from PySide6.QtWidgets import QPushButton

    from ui.metadata_screen import MetadataScreen
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    screen = MetadataScreen(store)
    qtbot.addWidget(screen)
    assert not [b for b in screen.findChildren(QPushButton) if "Apply" in b.text()]

    screen._populate_combos(["sid", "group"])
    screen._combos["session_id"].setCurrentIndex(1)  # "sid"
    screen.flush()
    assert store.manifest.mapping.rules.get("session_id") == "sid"


# ── all canonical fields, aliases, match summary, restore ───────────────────


def _store_with_sessions(tmp_path: Path, ids: list[str]):
    from track2data.core.models import SessionRef

    store = _make_store(tmp_path)
    store.update_sessions(
        [SessionRef(session_id=i, folder=tmp_path / i, sha256="") for i in ids]
    )
    return store


def test_every_canonical_field_has_a_mapping_row(qtbot) -> None:
    from track2data.metadata.schema import CANONICAL
    from ui.metadata_screen import MetadataScreen

    screen = MetadataScreen()
    qtbot.addWidget(screen)
    assert list(screen._combos) == CANONICAL


def test_individual_id_is_offered_and_auto_matches_its_aliases(qtbot) -> None:
    """Per-animal metadata is supported (D-010 superseded): the combo is enabled
    and a column like `fish_id` is matched to it automatically."""
    from ui.metadata_screen import MetadataScreen

    screen = MetadataScreen()
    qtbot.addWidget(screen)
    assert screen._combos["individual_id"].isEnabled()
    screen._populate_combos(["session_id", "fish_id", "weight"])
    assert screen._combos["individual_id"].currentText() == "fish_id"


def test_aliases_are_auto_matched_to_fields(qtbot) -> None:
    from ui.metadata_screen import MetadataScreen

    screen = MetadataScreen()
    qtbot.addWidget(screen)
    screen._populate_combos(["session_id", "condition", "date", "tank", "weight"])
    assert screen._combos["treatment"].currentText() == "condition"
    assert screen._combos["trial_date"].currentText() == "date"
    assert screen._combos["group_id"].currentText() == "tank"
    assert screen._combos["trial_id"].currentText() == "(skip)"


def test_match_summary_reports_matched_and_missing_sessions(qtbot, tmp_path: Path) -> None:
    from ui.metadata_screen import MetadataScreen

    csv_path = tmp_path / "meta.csv"
    csv_path.write_text("session_id,treatment\ns1,ctrl\ns2,drug\n", encoding="utf-8")
    store = _store_with_sessions(tmp_path, ["s1", "s2", "s3"])
    screen = MetadataScreen(store)
    qtbot.addWidget(screen)

    screen.load_path(csv_path)
    screen.flush()
    assert "2 of 3 sessions matched" in screen._match_label.text()
    assert "s3" in screen._match_label.text()


def test_reopened_project_repopulates_file_preview_and_mapping(qtbot, tmp_path: Path) -> None:
    from track2data.core.hashing import file_sha256
    from track2data.core.models import MappingRule, MetadataSource
    from ui.metadata_screen import MetadataScreen

    csv_path = tmp_path / "meta.csv"
    csv_path.write_text("sid,cond\ns1,ctrl\n", encoding="utf-8")
    store = _store_with_sessions(tmp_path, ["s1"])
    screen = MetadataScreen(store)
    qtbot.addWidget(screen)

    store.update_metadata_source(MetadataSource(path=csv_path, sha256=file_sha256(csv_path)))
    store.update_mapping(MappingRule(rules={"session_id": "sid", "treatment": "cond"}))

    assert screen._file_label.text() == "meta.csv"
    assert screen._preview.columnCount() == 2
    assert screen._combos["treatment"].currentText() == "cond"
    assert "1 of 1 sessions matched" in screen._match_label.text()


# ── per-animal controls ──────────────────────────────────────────────────────


def _per_animal_store(tmp_path: Path, labels=("1", "2"), n_animals=2):
    from track2data.core.models import SessionRef
    from ui.store.session_facts import SessionFacts

    store = _store_with_sessions(tmp_path, ["s1"])
    store.update_sessions([SessionRef(session_id="s1", folder=tmp_path / "s1", sha256="")])
    store._session_facts["s1"] = SessionFacts(
        session_id="s1", reader="idtrackerai", fps=30.0, n_frames=100, n_animals=n_animals,
        width_px=640, height_px=480, has_stable_identities=True,
        track_wo_identities=False, idtrackerai_version=None, length_unit=None,
        setup_points=None, roi_list=None, has_body_length=False, background_image_path=None,
        identities_labels=labels,
    )
    return store


def _write(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "meta.csv"
    path.write_text("session_id,fish,treatment,weight\n" + "\n".join(rows) + "\n")
    return path


def test_apply_mapping_keeps_unexposed_rule_fields(qtbot, tmp_path) -> None:
    """_apply_mapping used to rebuild the rule, resetting join_keys/join_regex."""
    from track2data.core.models import MappingRule
    from ui.metadata_screen import MetadataScreen

    store = _store_with_sessions(tmp_path, ["s1"])
    store.update_mapping(MappingRule(rules={}, join_keys=["tank", "date"], join_regex=r"(?P<a>x)"))
    screen = MetadataScreen(store)
    qtbot.addWidget(screen)
    screen._populate_combos(["session_id", "treatment"])
    screen.flush()
    rule = store.manifest.mapping
    assert rule.join_keys == ["tank", "date"] and rule.join_regex == r"(?P<a>x)"
    assert rule.rules.get("treatment") == "treatment"


def test_extra_columns_list_offers_unmapped_columns_and_commits(qtbot, tmp_path) -> None:
    from ui.metadata_screen import MetadataScreen

    store = _store_with_sessions(tmp_path, ["s1"])
    screen = MetadataScreen(store)
    qtbot.addWidget(screen)
    screen.load_path(_write(tmp_path, ["s1,1,ctrl,1.5"]))
    names = [screen._extra_list.item(i).text() for i in range(screen._extra_list.count())]
    # session_id and treatment are auto-mapped; "fish" is not a known alias
    assert names == ["fish", "weight"]
    screen._extra_list.item(1).setCheckState(Qt.CheckState.Checked)
    screen.flush()
    assert store.manifest.mapping.extra_columns == ["weight"]


def test_match_mode_is_enabled_only_with_an_individual_column(qtbot, tmp_path) -> None:
    from ui.metadata_screen import MetadataScreen

    store = _store_with_sessions(tmp_path, ["s1"])
    screen = MetadataScreen(store)
    qtbot.addWidget(screen)
    screen._populate_combos(["session_id", "treatment"])
    assert not screen._match_mode.isEnabled()
    screen._populate_combos(["session_id", "fish_id", "treatment"])
    assert screen._match_mode.isEnabled()
    screen._match_mode.setCurrentIndex(screen._match_mode.findData("index"))
    screen.flush()
    assert store.manifest.mapping.individual_match == "index"


def test_reopen_restores_extra_columns_and_match_mode(qtbot, tmp_path) -> None:
    from track2data.core.hashing import file_sha256
    from track2data.core.models import MappingRule, MetadataSource
    from ui.metadata_screen import MetadataScreen

    csv = _write(tmp_path, ["s1,1,ctrl,1.5"])
    store = _store_with_sessions(tmp_path, ["s1"])
    screen = MetadataScreen(store)
    qtbot.addWidget(screen)
    store.update_metadata_source(MetadataSource(path=csv, sha256=file_sha256(csv)))
    store.update_mapping(
        MappingRule(
            rules={"session_id": "session_id", "individual_id": "fish"},
            extra_columns=["weight"], individual_match="index",
        )
    )
    assert screen._combos["individual_id"].currentText() == "fish"
    assert screen._match_mode.currentData() == "index"
    checked = [
        screen._extra_list.item(i).text()
        for i in range(screen._extra_list.count())
        if screen._extra_list.item(i).checkState() == Qt.CheckState.Checked
    ]
    assert checked == ["weight"]


def _screen_with(qtbot, tmp_path, rows, **store_kw):
    from track2data.core.hashing import file_sha256
    from track2data.core.models import MappingRule, MetadataSource
    from ui.metadata_screen import MetadataScreen

    csv = _write(tmp_path, rows)
    store = _per_animal_store(tmp_path, **store_kw)
    screen = MetadataScreen(store)
    qtbot.addWidget(screen)
    store.update_metadata_source(MetadataSource(path=csv, sha256=file_sha256(csv)))
    store.update_mapping(
        MappingRule(rules={"session_id": "session_id", "individual_id": "fish"})
    )
    return screen, store


def test_summary_reports_animals_without_a_row(qtbot, tmp_path) -> None:
    screen, _ = _screen_with(qtbot, tmp_path, ["s1,1,ctrl,1.5"])
    text = screen._match_label.text()
    assert "1 of 1 sessions matched" in text
    assert "no row for animal 2" in text and "s1" in text


def test_summary_reports_keys_matching_no_animal(qtbot, tmp_path) -> None:
    screen, _ = _screen_with(qtbot, tmp_path, ["s1,1,ctrl,1.5", "s1,9,ctrl,2.5"])
    assert "'9'" in screen._match_label.text() and "matches no animal" in screen._match_label.text()


def test_summary_is_clean_when_every_animal_has_a_row(qtbot, tmp_path) -> None:
    screen, _ = _screen_with(qtbot, tmp_path, ["s1,1,ctrl,1.5", "s1,2,ctrl,2.5"])
    text = screen._match_label.text()
    assert "no row for animal" not in text and "matches no animal" not in text
    assert "2 animal rows matched" in text


def test_summary_warns_for_identity_free_sessions(qtbot, tmp_path) -> None:
    screen, store = _screen_with(qtbot, tmp_path, ["s1,1,ctrl,1.5", "s1,2,ctrl,2.5"])
    ref = store.manifest.sessions[0].model_copy(update={"identity_free_override": True})
    store.update_sessions([ref])
    assert "identity-free" in screen._match_label.text()
