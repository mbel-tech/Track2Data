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
        print(f"OK: {exe} was still running after {STARTUP_WINDOW_S}s -- smoke test passed.")
        return 0

    print(
        f"FAILED: {exe} exited on its own within {STARTUP_WINDOW_S}s "
        f"(return code {proc.returncode}) -- likely a missing hidden import.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
