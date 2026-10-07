#!/usr/bin/env python
"""Report what changed since the user guide was last updated.

    python .claude/skills/update-track2data-docs/changes.py [--since <git-rev>]

Baseline: the last commit that touched docs/guide/USER_GUIDE.md (override with --since).
Prints the commits since then, the CHANGELOG lines added, which source files changed, and which
guide chapters / screenshots those files affect. Read-only.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GUIDE = "docs/guide/USER_GUIDE.md"

# UI source file -> (guide chapter, screenshot name prefixes it can change)
SCREENS = {
    "ui/project_screen.py": ("1. Project", ["01-"]),
    "ui/import_screen.py": ("2. Sessions", ["02-"]),
    "ui/calibration_screen.py": ("3. Calibration", ["03-"]),
    "ui/dialogs/": ("3. Calibration / dialogs", ["03-", "04-"]),
    "ui/zones_screen.py": ("4. Zones", ["04-"]),
    "ui/metadata_screen.py": ("5. Metadata", ["05-"]),
    "ui/preprocessing_screen.py": ("6. Preprocessing", ["06-"]),
    "ui/metrics_screen.py": ("7. Metrics", ["07-"]),
    "ui/processing_screen.py": ("8. Processing", ["08-"]),
    "ui/preview_screen.py": ("9. Preview", ["09-"]),
    "ui/export_screen.py": ("10. Export", ["10-"]),
    "ui/widgets/": ("shared widgets: any screen", ["*"]),
    "ui/store/": ("shared state / badges: any screen", ["*"]),
    "app/": ("main window, menus, sidebar: any screen", ["*"]),
}
# Engine areas that change what the guide says about outputs, metrics or behaviour.
BEHAVIOUR = ("track2data/", "scripts/generate_guide_screenshots.py", "pyproject.toml")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help="baseline git revision (default: last guide commit)")
    since = ap.parse_args().since or git("log", "-1", "--format=%H", "--", GUIDE)
    print(f"Baseline: {git('log', '-1', '--format=%h %ad %s', '--date=short', since)}\n")

    print("== Commits since baseline ==")
    print(git("log", "--oneline", f"{since}..HEAD") or "(none)")

    print("\n== CHANGELOG lines added ==")
    diff = git("diff", f"{since}..HEAD", "--", "CHANGELOG.md")
    added = [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    print("\n".join(added) or "(none)")

    changed = git("diff", "--name-only", f"{since}..HEAD").splitlines()
    print("\n== UI changes -> chapters and screenshots to retake ==")
    hit = False
    for path in changed:
        for prefix, (chapter, shots) in SCREENS.items():
            if path.startswith(prefix):
                print(f"{path}\n    chapter: {chapter}   screenshots: {', '.join(shots)}")
                hit = True
    if not hit:
        print("(no UI source changed)")

    print("\n== Engine / behaviour files changed (check outputs, metrics, troubleshooting) ==")
    print("\n".join(p for p in changed if p.startswith(BEHAVIOUR)) or "(none)")

    print("\n== Other front-facing docs touched ==")
    front = ("README.md", "CONTRIBUTING.md", "docs/")
    print("\n".join(p for p in changed if p.startswith(front) and p != GUIDE) or "(none)")


if __name__ == "__main__":
    main()
