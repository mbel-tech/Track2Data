#!/usr/bin/env python
"""Build ``docs/guide/Track2Data_User_Guide.pdf`` from ``docs/guide/USER_GUIDE.md``.

The Markdown file is the single source of truth. This script renders it with pandoc, prints it to
PDF with headless Chromium, and stamps the PDF metadata (author, title, copyright).

Needs ``pandoc``, a Chromium/Chrome binary (``--chrome`` or ``$CHROME``) and ``pypdf``::

    python scripts/build_user_guide.py [--chrome /path/to/chrome]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUIDE = REPO / "docs" / "guide"
SOURCE = GUIDE / "USER_GUIDE.md"
PDF = GUIDE / "Track2Data_User_Guide.pdf"
BLOB = "https://github.com/mbel-tech/Track2Data/blob/main/"

AUTHOR = "Martina Bellio"
TITLE = "Track2Data User Guide"
COPYRIGHT = "© 2026 Martina Bellio"

CSS = """
@page { size: A4; margin: 20mm 18mm 22mm 18mm; }
body { font-family: "DejaVu Sans", "Helvetica Neue", Arial, sans-serif; font-size: 10pt;
       line-height: 1.5; color: #1b1f24; max-width: none; }
h1 { font-size: 24pt; border-bottom: 2px solid #2f6f9f; padding-bottom: 4pt; margin-top: 0; }
h1 + p, h1 { orphans: 3; }
h1:not(:first-of-type) { page-break-before: always; }
h2 { font-size: 16pt; color: #1f5a85; margin-top: 22pt; page-break-after: avoid; }
h3 { font-size: 12pt; color: #1f5a85; page-break-after: avoid; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.8pt; background: #f1f3f5;
       padding: 0 2pt; border-radius: 2pt; }
pre { background: #f1f3f5; padding: 8pt; border-radius: 4pt; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt; }
th, td { border: 1px solid #c8d0d8; padding: 3pt 6pt; text-align: left; vertical-align: top; }
th { background: #e8eff5; }
tr { page-break-inside: avoid; }
blockquote { margin: 8pt 0; padding: 2pt 10pt; border-left: 3pt solid #2f6f9f; background: #f4f8fb; }
figure { margin: 10pt 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; max-height: 85mm; border: 1px solid #c8d0d8; }
figcaption { font-size: 8.5pt; color: #4a5560; margin-top: 3pt; }
a { color: #1f5a85; text-decoration: none; }
hr { border: 0; border-top: 1px solid #c8d0d8; }
"""


def _absolutise_repo_links(text: str) -> str:
    """Links that leave the guide point at the repository on GitHub, so they work in the PDF."""

    def fix(match: re.Match[str]) -> str:
        target = match.group(2)
        resolved = (GUIDE / target.split("#")[0]).resolve()
        rel = resolved.relative_to(REPO).as_posix()
        suffix = "#" + target.split("#", 1)[1] if "#" in target else ""
        return f"{match.group(1)}({BLOB}{rel}{suffix})"

    return re.sub(r"(\])\((\.\./[^)\s]+)\)", fix, text)


def _find_chrome(explicit: str | None) -> str:
    candidates = [explicit, os.environ.get("CHROME")]
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        candidates.append(shutil.which(name))
    candidates += sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    raise SystemExit("No Chromium/Chrome found: pass --chrome or set $CHROME")


def build(chrome: str | None) -> Path:
    from pypdf import PdfReader, PdfWriter

    with tempfile.TemporaryDirectory(prefix="t2d_guide_pdf_") as tmp:
        tmpdir = Path(tmp)
        css = tmpdir / "guide.css"
        css.write_text(CSS, encoding="utf-8")
        md = GUIDE / ".USER_GUIDE.pdf-source.md"  # beside the images so relative paths resolve
        html = tmpdir / "guide.html"
        try:
            md.write_text(_absolutise_repo_links(SOURCE.read_text("utf-8")), encoding="utf-8")
            subprocess.run(
                ["pandoc", str(md), "-f", "gfm", "-t", "html5", "--standalone",
                 "--embed-resources", "--css", str(css), "--metadata", f"pagetitle={TITLE}",
                 "--metadata", f"author-meta={AUTHOR}",
                 "-o", str(html)],
                check=True, cwd=GUIDE,
            )
        finally:
            md.unlink(missing_ok=True)
        raw = tmpdir / "raw.pdf"
        subprocess.run(
            [_find_chrome(chrome), "--headless=new", "--no-sandbox", "--disable-gpu",
             "--no-pdf-header-footer", f"--print-to-pdf={raw}", html.as_uri()],
            check=True, capture_output=True,
        )
        reader = PdfReader(raw)
        writer = PdfWriter(clone_from=reader)
        writer.add_metadata({
            "/Title": TITLE,
            "/Author": AUTHOR,
            "/Subject": "User guide for the Track2Data desktop application",
            "/Keywords": "Track2Data, idtracker.ai, user guide, animal tracking",
            "/Creator": "Track2Data scripts/build_user_guide.py",
            "/Producer": "pandoc + Chromium + pypdf",
            "/Copyright": COPYRIGHT,
        })
        with PDF.open("wb") as fh:
            writer.write(fh)
    return PDF


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chrome", help="path to a Chromium/Chrome binary")
    print(f"wrote {build(ap.parse_args().chrome)}")
