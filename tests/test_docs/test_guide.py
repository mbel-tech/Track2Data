"""The user guide must not rot: every screen is covered, every image it shows exists, every link works.

The guide is one Markdown file, docs/guide/USER_GUIDE.md. Screenshots are produced by
scripts/generate_guide_screenshots.py; this test only checks that the Markdown and the committed
images agree. The PDF is built by scripts/build_user_guide.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "guide"
TEXT = (GUIDE / "USER_GUIDE.md").read_text(encoding="utf-8")
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
_IMG = re.compile(r'<img src="([^"]+)"|!\[[^\]]*\]\(([^)\s]+)\)')


def _images() -> list[str]:
    return [a or b for a, b in _IMG.findall(TEXT)]


def _anchors() -> set[str]:
    """GitHub-style heading anchors."""
    out = set()
    for line in TEXT.splitlines():
        m = re.match(r"#{1,6}\s+(.*)", line)
        if m:
            slug = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-")
            out.add(slug)
    return out


def test_guide_has_title_and_copyright() -> None:
    assert TEXT.startswith("# Track2Data User Guide")
    assert "© 2026 Martina Bellio" in TEXT


def test_there_is_a_chapter_for_every_wizard_screen() -> None:
    from ui.store.stage_status import PAGE_NAMES

    chapters = re.findall(r"^## (\d+)\. (.+)$", TEXT, flags=re.M)
    assert len(chapters) == len(PAGE_NAMES)
    for (num, title), name in zip(chapters, PAGE_NAMES, strict=True):
        assert name.lower() in title.lower(), f"chapter {num} should document the {name} screen"


def test_every_image_exists_and_every_committed_image_is_used() -> None:
    shown = {Path(t).name for t in _images()}
    for t in _images():
        assert (GUIDE / t).exists(), f"image {t} is missing"
    on_disk = {p.name for p in (GUIDE / "images").glob("*.png")}
    assert on_disk == shown, f"unused: {sorted(on_disk - shown)}, missing: {sorted(shown - on_disk)}"


def test_every_chapter_shows_at_least_one_screenshot() -> None:
    chapters = re.split(r"^## ", TEXT, flags=re.M)
    for chapter in chapters:
        if re.match(r"\d+\. ", chapter):
            assert _IMG.search(chapter), f"chapter '{chapter.splitlines()[0]}' has no screenshot"


@pytest.mark.parametrize("target", sorted({t for t in _LINK.findall(TEXT)}))
def test_every_link_resolves(target: str) -> None:
    if target.startswith(("http://", "https://", "mailto:")):
        return
    if target.startswith("#"):
        assert target[1:] in _anchors(), f"anchor {target} has no heading"
        return
    assert (GUIDE / target.split("#")[0]).resolve().exists(), f"link {target} is missing"


def test_screenshot_script_and_guide_agree_on_image_names() -> None:
    """Each image the guide shows is one the generator script writes."""
    script = (GUIDE.parents[1] / "scripts" / "generate_guide_screenshots.py").read_text("utf-8")
    written = set(re.findall(r'shot\("([^"]+)"', script))
    shown = {Path(t).stem for t in _images()}
    assert shown <= written, f"guide shows images the script does not write: {sorted(shown - written)}"


def test_pdf_is_committed_with_author_metadata() -> None:
    pypdf = pytest.importorskip("pypdf")
    meta = pypdf.PdfReader(GUIDE / "Track2Data_User_Guide.pdf").metadata
    assert meta.author == "Martina Bellio"
    assert meta.title == "Track2Data User Guide"
