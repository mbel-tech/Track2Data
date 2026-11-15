"""
Launches the just-built Track2Data executable and confirms it stays
alive (doesn't crash on startup -- e.g. from a missing hidden import
PyInstaller's static analysis couldn't see) for a few seconds, then
kills it. Used by the release workflow's build job (issue #43) right
after the PyInstaller build step, before wrapping the result into an
installer/.dmg/.AppImage -- no point packaging a binary that can't
even launch.

Cross-platform via subprocess + a plain sleep/poll loop rather than
shell job control (bash's `kill -0 $!` behaves inconsistently for GUI
processes across Windows/macOS/Linux runners).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

STARTUP_WINDOW_S = 8


def _executable_path() -> Path:
    if sys.platform == "win32":
        return Path("dist/Track2Data.exe")
    if sys.platform == "darwin":
        return Path("dist/Track2Data.app/Contents/MacOS/Track2Data")
    return Path("dist/Track2Data")


SELF_CHECK_TIMEOUT_S = 120


def _self_check(exe: Path, env: dict[str, str]) -> int:
    """Run ``exe --self-check``: a real export through every built-in exporter.

    Staying alive proves the GUI imports resolved; it says nothing about the
    exporters, which register quietly and are simply absent when PyInstaller
    leaves a module out.
    """
    try:
        result = subprocess.run(
            [str(exe), "--self-check"], env=env, timeout=SELF_CHECK_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        print(f"FAILED: {exe} --self-check timed out", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(
            f"FAILED: {exe} --self-check returned {result.returncode} "
            "-- a built-in exporter is missing from the build or failed to write.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {exe} --self-check exported through every built-in exporter.")
    return 0


def main() -> int:
    exe = _executable_path()
    if not exe.exists():
        print(f"error: {exe} does not exist", file=sys.stderr)
        return 1

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.Popen([str(exe)], env=env)

    time.sleep(STARTUP_WINDOW_S)
    still_running = proc.poll() is None

    if still_running:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"OK: {exe} was still running after {STARTUP_WINDOW_S}s.")
        return _self_check(exe, env)

    print(
        f"FAILED: {exe} exited on its own within {STARTUP_WINDOW_S}s "
        f"(return code {proc.returncode}) -- likely a missing hidden import.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
