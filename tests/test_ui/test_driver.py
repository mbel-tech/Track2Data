"""The GUI driver's scan / confirm / shot-dialog verbs.

The driver (.claude/skills/run-track2data/driver.py) drives the real window in-process so a reader's
confirm flow can be seen and checked without a display. These tests run each verb for real, because
a driver that silently stops working is only noticed when someone needs it.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QFileDialog, QMessageBox

DRIVER = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "run-track2data" / "driver.py"


@pytest.fixture
def driver_module() -> Iterator[ModuleType]:
    """The driver, with every Qt dialog method it patches put back afterwards."""
    saved = {
        (cls, name): cls.__dict__[name]
        for cls in (QMessageBox, QFileDialog)
        for name in (
            "warning",
            "critical",
            "information",
            "question",
            "exec",
            "open",
            "getExistingDirectory",
            "getExistingDirectoryUrl",
            "getOpenFileName",
            "getOpenFileNames",
            "getSaveFileName",
        )
        if name in cls.__dict__
    }
    spec = importlib.util.spec_from_file_location("t2d_driver", DRIVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MODALS.clear()
    yield module
    for (cls, name), original in saved.items():
        setattr(cls, name, original)


@pytest.fixture
def idtracker_root(tiny_real_session: Path, tmp_path: Path) -> Path:
    root = tmp_path / "root"
    for name in ("s1", "s2"):
        shutil.copytree(tiny_real_session, root / name)
    return root


def args(module: ModuleType, **kw) -> argparse.Namespace:
    base = {"paths": [], "option": [], "shot": None, "out": None, "workdir": None}
    base.update(kw)
    return argparse.Namespace(**base)


class TestTheFileDialogGuard:
    def test_a_file_dialog_cannot_hang_the_driver(self, qtbot, driver_module) -> None:
        driver_module.install_modal_guard()
        assert QFileDialog.getExistingDirectory(None, "pick") == ""
        assert QFileDialog.getOpenFileName(None, "pick") == ("", "")
        assert any("pick" in m for m in driver_module.MODALS)

    def test_an_instance_dialog_returns_at_once_as_cancelled(self, qtbot, driver_module) -> None:
        driver_module.install_modal_guard()
        dialog = QFileDialog()
        assert dialog.exec() == QFileDialog.DialogCode.Rejected


class TestScan:
    def test_it_reports_what_the_dialog_would_show(
        self, qtbot, driver_module, idtracker_root: Path, tmp_path: Path, capsys
    ) -> None:
        code = driver_module.cmd_scan(args(driver_module, paths=[idtracker_root], workdir=tmp_path))
        out = capsys.readouterr().out
        assert code == 0
        assert "idtracker.ai" in out and "High" in out
        assert "s1" in out and "s2" in out
        assert "Add 2 sessions" in out

    def test_nothing_is_added_by_scanning(
        self, qtbot, driver_module, idtracker_root: Path, tmp_path: Path
    ) -> None:
        drv = driver_module.Driver()
        try:
            drv.new_project(tmp_path)
            dialog = drv.scan(idtracker_root)
            assert dialog is not None and drv.win._store.manifest.sessions == []
        finally:
            drv.close()

    def test_a_folder_of_junk_says_so_and_still_exits_cleanly(
        self, qtbot, driver_module, tmp_path: Path, capsys
    ) -> None:
        junk = tmp_path / "junk"
        junk.mkdir()
        (junk / "run.slp").write_text("x")
        code = driver_module.cmd_scan(args(driver_module, paths=[junk], workdir=tmp_path))
        out = capsys.readouterr().out
        assert code == 0
        assert "No tracking output" in out and "SLEAP project" in out

    def test_it_can_write_a_picture_of_the_dialog(
        self, qtbot, driver_module, idtracker_root: Path, tmp_path: Path
    ) -> None:
        shot = tmp_path / "shots" / "dialog.png"
        driver_module.cmd_scan(
            args(driver_module, paths=[idtracker_root], workdir=tmp_path, shot=str(shot))
        )
        assert shot.exists() and shot.stat().st_size > 1000


class TestConfirm:
    def test_it_adds_the_sessions_and_says_so(
        self, qtbot, driver_module, idtracker_root: Path, tmp_path: Path, capsys
    ) -> None:
        code = driver_module.cmd_confirm(
            args(driver_module, paths=[idtracker_root], workdir=tmp_path)
        )
        assert code == 0
        assert "Added 2 sessions" in capsys.readouterr().out

    def test_the_added_sessions_carry_the_reader(
        self, qtbot, driver_module, idtracker_root: Path, tmp_path: Path
    ) -> None:
        drv = driver_module.Driver()
        try:
            drv.new_project(tmp_path)
            drv.scan(idtracker_root)
            assert drv.confirm() == 2
            refs = drv.win._store.manifest.sessions
            assert {r.reader for r in refs} == {"idtrackerai"}
        finally:
            drv.close()

    def test_a_missing_option_blocks_it_and_the_exit_code_says_so(
        self, qtbot, driver_module, toy_reader, toy_folder: Path, tmp_path: Path, capsys
    ) -> None:
        code = driver_module.cmd_confirm(args(driver_module, paths=[toy_folder], workdir=tmp_path))
        out = capsys.readouterr().out
        assert code != 0
        assert "Frame rate" in out

    def test_options_given_on_the_command_line_unblock_it(
        self, qtbot, driver_module, toy_reader, toy_folder: Path, tmp_path: Path, capsys
    ) -> None:
        code = driver_module.cmd_confirm(
            args(
                driver_module,
                paths=[toy_folder],
                workdir=tmp_path,
                option=["fps=25", "width_px=100", "height_px=80"],
            )
        )
        assert code == 0
        assert "Added 1 session" in capsys.readouterr().out

    def test_an_unknown_option_is_refused_by_name(
        self, qtbot, driver_module, toy_reader, toy_folder: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(SystemExit, match="nonsense"):
            driver_module.cmd_confirm(
                args(driver_module, paths=[toy_folder], workdir=tmp_path, option=["nonsense=1"])
            )


class TestShotDialog:
    def test_it_writes_the_dialog_not_the_whole_window(
        self, qtbot, driver_module, idtracker_root: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "dialog.png"
        code = driver_module.cmd_shot_dialog(
            args(driver_module, paths=[idtracker_root], workdir=tmp_path, out=str(out))
        )
        assert code == 0 and out.exists()

    def test_the_empty_state_can_be_photographed_too(
        self, qtbot, driver_module, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        out = tmp_path / "empty.png"
        driver_module.cmd_shot_dialog(
            args(driver_module, paths=[empty], workdir=tmp_path, out=str(out))
        )
        assert out.exists()
