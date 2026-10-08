#!/usr/bin/env python
"""
Programmatic driver for the Track2Data PySide6 GUI.

Drives the real MainWindow in-process: navigates the wizard, clicks
widgets, and writes screenshots -- with no display, no window manager,
and no dependence on where (or whether) a window actually appears on a
physical monitor.

Why in-process rather than OS-level window capture: capturing by window
handle means dealing with whichever monitor the window landed on. On a
multi-monitor setup a secondary display can sit at *negative* desktop
coordinates, so a naive "screenshot the primary screen" grab returns a
picture with no app in it at all -- which reads as "the app failed to
launch" when it launched fine. QWidget.grab() renders the widget
straight to a pixmap through Qt's paint system, so it sidesteps screens
entirely and behaves identically on a dev box and in headless CI.

Usage (paths relative to the repo root):

    python .claude/skills/run-track2data/driver.py smoke
    python .claude/skills/run-track2data/driver.py pages
    python .claude/skills/run-track2data/driver.py shot --page 7 -o out.png
    python .claude/skills/run-track2data/driver.py repl

Adding sessions (scan -> confirm dialog -> add), as a user would, without a display:

    driver.py scan PATH... [--shot dialog.png]        what the confirm dialog shows
    driver.py confirm PATH... [--option fps=25 ...]   scan, fill options, press Add
    driver.py shot-dialog PATH... -o dialog.png       picture of the dialog only
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

# ── Qt environment: must be set BEFORE PySide6 is imported ────────────────
#
# offscreen: renders without a display server. Works everywhere, and
# means this driver never fights a window manager.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Qt 6 ships no fonts of its own, and the offscreen platform plugin has
# no system font path wired up. Without this, every glyph renders as a
# tofu box (□□□□) -- the layout is pixel-correct but completely
# unreadable, which is a confusing thing to stare at in a screenshot.
# Point Qt at the OS font directory explicitly.
_FONT_DIRS = {
    "win32": r"C:\Windows\Fonts",
    "darwin": "/System/Library/Fonts",
}
if "QT_QPA_FONTDIR" not in os.environ:
    _candidate = _FONT_DIRS.get(sys.platform, "/usr/share/fonts")
    if Path(_candidate).is_dir():
        os.environ["QT_QPA_FONTDIR"] = _candidate

from PySide6.QtWidgets import (  # noqa: E402  -- must follow the env setup above
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

# Modal dialogs recorded by install_modal_guard(), newest last.
MODALS: list[str] = []


def install_modal_guard() -> None:
    """Stop modal dialogs from hanging the driver forever.

    A QMessageBox spins its own event loop until someone clicks it. With
    no display and no user there is nobody to click, so an unexpected
    validation warning turns into a silent infinite hang -- no traceback,
    no output, just a process that never returns. That is genuinely hard
    to diagnose from the outside.

    Replace the static helpers with recorders that return a default
    answer immediately, so an unexpected dialog shows up as a printed
    line instead of a wedged process.
    """

    def _recorder(kind: str, default):
        def _handler(_parent=None, title="", text="", *args, **kwargs):
            MODALS.append(f"{kind}: {title} -- {text}")
            print(f"  [modal intercepted] {kind}: {title} -- {text}", flush=True)
            return default

        return staticmethod(_handler)

    QMessageBox.warning = _recorder("warning", QMessageBox.StandardButton.Ok)
    QMessageBox.critical = _recorder("critical", QMessageBox.StandardButton.Ok)
    QMessageBox.information = _recorder("information", QMessageBox.StandardButton.Ok)
    QMessageBox.question = _recorder("question", QMessageBox.StandardButton.Yes)
    QMessageBox.exec = lambda self, *a, **k: (  # type: ignore[method-assign]
        MODALS.append(f"exec: {self.text()}"),
        print(f"  [modal intercepted] exec: {self.text()}", flush=True),
        QMessageBox.StandardButton.Ok,
    )[-1]

    # A file picker blocks exactly like a message box, and "Add Folders..." opens one. Every way of
    # opening one answers "cancelled" at once; drive the flow with `scan` / `confirm` instead.
    def _picker(name: str, cancelled):
        def _handler(*args, **kwargs):
            title = next((a for a in args if isinstance(a, str)), "")
            MODALS.append(f"file dialog: {name} -- {title}")
            print(f"  [modal intercepted] file dialog: {name} -- {title}", flush=True)
            return cancelled

        return staticmethod(_handler)

    for name, cancelled in (
        ("getExistingDirectory", ""),
        ("getOpenFileName", ("", "")),
        ("getOpenFileNames", ([], "")),
        ("getSaveFileName", ("", "")),
    ):
        setattr(QFileDialog, name, _picker(name, cancelled))

    def _instance_exec(self, *_a, **_k):
        MODALS.append("file dialog: exec")
        print("  [modal intercepted] file dialog: exec", flush=True)
        return QFileDialog.DialogCode.Rejected

    QFileDialog.exec = _instance_exec  # type: ignore[method-assign]


# Index -> label. Mirrors the `pages` list in app/main_window.py; the
# sidebar shows 7 numbered stages but the stack holds 10 widgets, so
# these are stack indices, not the numbers the sidebar displays.
PAGES = [
    "project",
    "import",
    "calibration",
    "zones",
    "metadata",
    "preprocessing",
    "metrics",
    "processing",
    "preview",
    "export",
]

WINDOW_SIZE = (1216, 759)

# A window whose render collapses to a couple of flat colours never
# actually painted. Real Track2Data pages sample ~40+ distinct colours.
MIN_DISTINCT_COLOURS = 8
# A dialog is mostly plain background (its empty state is a few lines of text), so it is held to
# a lower bar. A dialog that never painted samples one colour.
MIN_DIALOG_COLOURS = 3


class Driver:
    """Owns the QApplication and MainWindow for one session."""

    def __init__(self) -> None:
        install_modal_guard()
        self.app = QApplication.instance() or QApplication([])
        from app.main_window import MainWindow

        self.win = MainWindow()
        self.win.resize(*WINDOW_SIZE)
        self.win.show()
        self.pump()

    def pump(self, rounds: int = 3) -> None:
        """Let Qt process pending events so layout/paint settle.

        Without this, a freshly-shown or just-switched page can grab as
        a half-laid-out frame.
        """
        for _ in range(rounds):
            self.app.processEvents()

    # ── navigation ────────────────────────────────────────────────────

    def goto(self, page: int | str) -> int:
        # argparse and the REPL both hand this over as a string, so "7"
        # and "processing" have to work equally well -- resolve digits as
        # an index before falling back to a name lookup.
        if isinstance(page, str):
            page = page.strip()
            if page.lstrip("-").isdigit():
                index = int(page)
            elif page in PAGES:
                index = PAGES.index(page)
            else:
                raise SystemExit(f"unknown page {page!r}; have: {', '.join(PAGES)}")
        else:
            index = int(page)
        if not 0 <= index < len(PAGES):
            raise SystemExit(f"page out of range: {index} (have 0..{len(PAGES) - 1})")
        self.win._go_to_page(index)
        self.pump()
        return index

    def current_page(self) -> int:
        return self.win._stack.currentIndex()

    # ── widget access ─────────────────────────────────────────────────

    def page_widget(self, index: int | None = None):
        return self.win._stack.widget(self.current_page() if index is None else index)

    def button(self, label: str, page: int | None = None) -> QPushButton:
        """Find a QPushButton on a page by its visible text.

        Matched loosely (case-insensitive substring) because several
        labels carry a trailing ellipsis -- "Open Project…" -- and the
        character used for it is easy to get wrong from the outside.
        """
        target = label.casefold()
        for btn in self.page_widget(page).findChildren(QPushButton):
            if target in btn.text().casefold():
                return btn
        available = [b.text() for b in self.page_widget(page).findChildren(QPushButton)]
        raise SystemExit(f"no button matching {label!r}; page has: {available}")

    def click(self, label: str, page: int | None = None) -> None:
        self.button(label, page).click()
        self.pump()

    def type_into(self, text: str, page: int | None = None, nth: int = 0) -> None:
        edits = self.page_widget(page).findChildren(QLineEdit)
        if len(edits) <= nth:
            raise SystemExit(f"page has {len(edits)} QLineEdit(s); wanted index {nth}")
        edits[nth].setText(text)
        self.pump()

    # ── capture ───────────────────────────────────────────────────────

    def shot(self, out_path: str | Path) -> Path:
        """Screenshot the whole main window; fail loudly on a dud frame."""
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        return self._save(self.win.grab(), out)

    def _save(self, pixmap, out: Path, min_colours: int = MIN_DISTINCT_COLOURS) -> Path:
        # QPixmap.save() returns False rather than raising -- notably when
        # the parent directory doesn't exist. Silently producing no file
        # is the worst outcome here, so check it.
        if not pixmap.save(str(out)):
            raise SystemExit(f"QPixmap.save() refused to write {out}")

        image = pixmap.toImage()
        colours = set()
        for y in range(0, image.height(), 7):
            for x in range(0, image.width(), 7):
                colours.add(image.pixel(x, y))
        if len(colours) < min_colours:
            raise SystemExit(
                f"{out} looks blank ({len(colours)} distinct colours sampled). "
                "The window did not paint."
            )
        return out

    # ── adding sessions: scan -> confirm dialog -> add ────────────────

    def new_project(self, directory: str | Path, name: str = "driver_project") -> None:
        """Create a project the way the Project screen does (never through its file picker)."""
        self.goto("project")
        self.type_into(name)
        self.page_widget()._selected_dir = str(directory)
        self.click("Create Project")
        if not self.win._store.has_project:
            raise SystemExit(f"could not create a project in {directory}: {MODALS[-1:]}")

    @property
    def import_screen(self):
        return self.win._stack.widget(PAGES.index("import"))

    def scan(self, *paths: str | Path, timeout: float = 60.0):
        """Point the Sessions screen at *paths* and wait for the confirm dialog.

        Returns the open dialog, or None when the scan failed (the screen then shows why).
        """
        self.goto("import")
        screen = self.import_screen
        screen._import_paths([Path(p) for p in paths])
        deadline = time.monotonic() + timeout
        while screen._scan_id is not None:
            if time.monotonic() > deadline:
                raise SystemExit(f"the scan did not finish within {timeout:.0f} s")
            self.pump(1)
            time.sleep(0.01)
        self.pump()
        return screen._dialog

    def set_option(self, dialog, assignment: str) -> None:
        """Set one option in the dialog's form, as typing it would (``name=value``)."""
        name, sep, value = assignment.partition("=")
        form = dialog.options_form
        try:
            control = form.widget_for(name.strip())
        except KeyError:
            known = ", ".join(sorted(form.values()) or ["none"]) if form.is_empty else ""
            raise SystemExit(
                f"unknown option {name!r} for this software" + (f" ({known})" if known else "")
            ) from None
        if not sep:
            raise SystemExit(f"option {assignment!r} must look like name=value")
        if isinstance(control, QDoubleSpinBox | QSpinBox):
            control.setValue(float(value) if isinstance(control, QDoubleSpinBox) else int(value))
        elif isinstance(control, QCheckBox):
            control.setChecked(value.strip().lower() in {"1", "true", "yes", "on"})
        elif isinstance(control, QComboBox):
            control.setCurrentText(value)
        elif isinstance(control, QLineEdit):
            control.setText(value)
        else:
            raise SystemExit(f"option {name!r} cannot be set from the command line")
        self.pump()

    def confirm(self) -> int:
        """Press Add in the open dialog; returns how many sessions were added.

        Refuses, with the reasons the dialog itself gives, when Add is disabled.
        """
        dialog = self.import_screen._dialog
        if dialog is None:
            raise SystemExit(
                "no confirm dialog is open (nothing was recognised, or the scan failed)"
            )
        if not dialog.ok_button.isEnabled():
            raise SystemExit(
                "cannot add yet:\n  " + dialog.ok_button.toolTip().replace("\n", "\n  ")
            )
        before = len(self.win._store.manifest.sessions)
        dialog.ok_button.click()
        self.pump()
        return len(self.win._store.manifest.sessions) - before

    def shot_dialog(self, out_path: str | Path) -> Path:
        """Screenshot the confirm dialog on its own."""
        dialog = self.import_screen._dialog
        if dialog is None:
            raise SystemExit("no confirm dialog is open to photograph")
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        return self._save(dialog.grab(), out, MIN_DIALOG_COLOURS)

    def describe_dialog(self) -> str:
        """The dialog's state as text: what a person looking at it would read."""
        screen = self.import_screen
        dialog = screen._dialog
        if dialog is None:
            return screen._scan_message.text() or "No dialog is open."
        lines = [dialog.summary_label.text()]
        if dialog.draft.is_empty:
            lines.append(
                dialog.empty_label.text()
                .replace("<br>", "\n")
                .replace("<b>", "")
                .replace("</b>", "")
            )
            return "\n".join(lines)
        lines.append(
            f"Software: {dialog.reader_combo.currentText()} - {dialog.confidence_label.text()}"
        )
        if not dialog.unverified_label.isHidden():
            lines.append("  (unverified: not yet checked against real output)")
        lines.append(dialog.evidence_label.text())
        for name, value in dialog.options_form.values().items():
            lines.append(f"  option {name} = {value}")
        for row in range(dialog.table.rowCount()):
            ident = dialog.table.item(row, 1).text()
            source = dialog.table.item(row, 2).text()
            lines.append(f"  session {ident}  <- {source}")
        if dialog.ok_button.isEnabled():
            lines.append(dialog.ok_button.text())
        else:
            lines.append(f"{dialog.ok_button.text()} (disabled)")
            lines.append("  " + dialog.problems_label.text())
        return "\n".join(lines)

    def close(self) -> None:
        # Cancels any in-flight background task and waits for the pool to
        # drain. Skipping it can crash the interpreter on exit: a pool
        # thread emitting a Qt signal into a half-destroyed widget tree
        # dies without a Python traceback.
        self.win.close()
        self.pump()


# ── commands ──────────────────────────────────────────────────────────────


def cmd_pages(_args: argparse.Namespace) -> int:
    for i, name in enumerate(PAGES):
        print(f"{i}\t{name}")
    return 0


def cmd_shot(args: argparse.Namespace) -> int:
    drv = Driver()
    drv.goto(args.page)
    out = drv.shot(args.out)
    print(f"wrote {out}")
    drv.close()
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    """Launch, drive a real flow, screenshot every page, verify state."""
    out_dir = Path(args.out_dir).resolve()
    drv = Driver()
    print(
        f"platform={os.environ['QT_QPA_PLATFORM']} "
        f"fontdir={os.environ.get('QT_QPA_FONTDIR', '(unset)')}"
    )

    store = drv.win._store
    assert not store.has_project, "expected no project open at startup"

    # Real user flow: name a project, create it, confirm the store changed.
    # Deliberately not via QFileDialog -- a modal file picker blocks
    # forever with nothing to click it. Set the directory on the store
    # instead, the way the dialog's callback would.
    drv.goto("project")
    before = drv.shot(out_dir / "01-project-empty.png")
    print(f"  {before.name}")

    drv.type_into("smoke_project")
    # The chosen directory lives on the ProjectScreen widget as
    # _selected_dir, NOT on the store -- _create_project() validates that
    # attribute before it ever touches the store. Setting the store's
    # _project_dir instead leaves _selected_dir empty, so validation
    # fails and pops a modal warning. This is what the Browse… dialog's
    # callback assigns.
    drv.page_widget()._selected_dir = str(out_dir)
    drv.click("Create Project")

    if MODALS:
        raise SystemExit(f"unexpected modal dialog during create: {MODALS[-1]}")

    if not store.has_project:
        raise SystemExit("clicking 'Create Project' did not open a project")
    name = store.manifest.project_name
    if name != "smoke_project":
        raise SystemExit(f"project name is {name!r}, expected 'smoke_project'")
    print(f"  project created: {name!r}  has_project={store.has_project}")

    after = drv.shot(out_dir / "02-project-created.png")
    print(f"  {after.name}")

    # Every page must render without throwing and without a blank frame.
    for index, page_name in enumerate(PAGES):
        drv.goto(index)
        shot = drv.shot(out_dir / f"page-{index}-{page_name}.png")
        print(f"  {shot.name}")

    drv.close()
    print(f"\nOK -- {len(PAGES) + 2} screenshots in {out_dir}")
    return 0


def _open_scan(args: argparse.Namespace):
    """A driver with a throwaway project, pointed at args.paths. Returns (driver, dialog)."""
    drv = Driver()
    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="t2d-driver-"))
    drv.new_project(workdir)
    dialog = drv.scan(*args.paths)
    return drv, dialog


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan and print what the confirm dialog shows; add nothing."""
    drv, _dialog = _open_scan(args)
    try:
        print(drv.describe_dialog())
        if args.shot and drv.import_screen._dialog is not None:
            print(f"wrote {drv.shot_dialog(args.shot)}")
        return 0
    finally:
        drv.close()


def cmd_confirm(args: argparse.Namespace) -> int:
    """Scan, apply --option name=value, press Add. Non-zero when adding is blocked."""
    drv, dialog = _open_scan(args)
    try:
        if dialog is None:
            print(drv.describe_dialog())
            return 1
        for assignment in args.option:
            drv.set_option(dialog, assignment)
        try:
            added = drv.confirm()
        except SystemExit as exc:
            print(drv.describe_dialog())
            print(exc)
            return 1
        print(f"Added {added} session{'s' if added != 1 else ''}")
        return 0
    finally:
        drv.close()


def cmd_shot_dialog(args: argparse.Namespace) -> int:
    """Scan and write a picture of the confirm dialog (also its empty state)."""
    drv, _dialog = _open_scan(args)
    try:
        print(f"wrote {drv.shot_dialog(args.out)}")
        return 0
    finally:
        drv.close()


def cmd_repl(_args: argparse.Namespace) -> int:
    """Line-oriented REPL, for driving the app from tmux or a pipe.

    Commands: goto <page> | click <label> | type <text> | shot <path>
              scan <path> | option <name=value> | confirm | shot-dialog <path>
              state | pages | quit
    """
    drv = Driver()
    print("ready", flush=True)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        verb, _, rest = line.partition(" ")
        try:
            if verb == "quit":
                break
            elif verb == "goto":
                print(f"page {drv.goto(rest.strip())}", flush=True)
            elif verb == "click":
                drv.click(rest.strip())
                print("clicked", flush=True)
            elif verb == "type":
                drv.type_into(rest)
                print("typed", flush=True)
            elif verb == "shot":
                print(f"wrote {drv.shot(rest.strip())}", flush=True)
            elif verb == "scan":
                if drv.win._store.has_project is False:
                    drv.new_project(tempfile.mkdtemp(prefix="t2d-driver-"))
                drv.scan(rest.strip())
                print(drv.describe_dialog(), flush=True)
            elif verb == "option":
                dialog = drv.import_screen._dialog
                if dialog is None:
                    raise SystemExit("no confirm dialog is open")
                drv.set_option(dialog, rest.strip())
                print(drv.describe_dialog(), flush=True)
            elif verb == "confirm":
                print(f"added {drv.confirm()}", flush=True)
            elif verb == "shot-dialog":
                print(f"wrote {drv.shot_dialog(rest.strip())}", flush=True)
            elif verb == "pages":
                print(", ".join(f"{i}:{n}" for i, n in enumerate(PAGES)), flush=True)
            elif verb == "state":
                store = drv.win._store
                print(
                    f"page={drv.current_page()} has_project={store.has_project} "
                    f"name={store.manifest.project_name if store.has_project else None}",
                    flush=True,
                )
            else:
                print(f"unknown command: {verb}", flush=True)
        except SystemExit as exc:  # keep the REPL alive on a bad command
            print(f"error: {exc}", flush=True)
    drv.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pages", help="list wizard page indices").set_defaults(func=cmd_pages)

    p_smoke = sub.add_parser("smoke", help="launch, drive a flow, screenshot everything")
    p_smoke.add_argument("--out-dir", default="artifacts/gui-smoke")
    p_smoke.set_defaults(func=cmd_smoke)

    p_shot = sub.add_parser("shot", help="screenshot one page")
    p_shot.add_argument("--page", default="project", help="index or name")
    p_shot.add_argument("-o", "--out", required=True)
    p_shot.set_defaults(func=cmd_shot)

    def _scan_args(sub_parser: argparse.ArgumentParser) -> None:
        sub_parser.add_argument("paths", nargs="+", help="folder(s) or file(s) to scan")
        sub_parser.add_argument(
            "--workdir", help="where the throwaway project goes (default: temp)"
        )

    p_scan = sub.add_parser("scan", help="scan folders and print what the confirm dialog shows")
    _scan_args(p_scan)
    p_scan.add_argument("--shot", help="also write a picture of the dialog here")
    p_scan.set_defaults(func=cmd_scan)

    p_confirm = sub.add_parser("confirm", help="scan, fill options, press Add")
    _scan_args(p_confirm)
    p_confirm.add_argument(
        "--option", action="append", default=[], metavar="NAME=VALUE", help="set a reader option"
    )
    p_confirm.set_defaults(func=cmd_confirm)

    p_dialog = sub.add_parser("shot-dialog", help="scan and screenshot the confirm dialog")
    _scan_args(p_dialog)
    p_dialog.add_argument("-o", "--out", required=True)
    p_dialog.set_defaults(func=cmd_shot_dialog)

    sub.add_parser("repl", help="stdin command loop").set_defaults(func=cmd_repl)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
