"""The user guide must not rot: every page exists, every image it shows exists, every link works.

Screenshots are produced by scripts/generate_guide_screenshots.py; this test only checks that the
Markdown and the committed images agree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "guide"
PAGES = [
    "README.md",
    "01-project.md",
    "02-sessions.md",
    "03-calibration.md",
    "04-zones.md",
    "05-metadata.md",
    "06-preprocessing.md",
    "07-metrics.md",
    "08-processing.md",
    "09-preview.md",
    "10-export.md",
    "outputs.md",
    "troubleshooting.md",
]
_LINK = re.compile(r"(!?)\[[^\]]*\]\(([^)\s]+)\)")


def _links(page: str) -> list[tuple[bool, str]]:
    text = (GUIDE / page).read_text(encoding="utf-8")
    return [(bool(bang), target) for bang, target in _LINK.findall(text)]


@pytest.mark.parametrize("page", PAGES)
def test_page_exists_and_is_not_empty(page: str) -> None:
    assert (GUIDE / page).read_text(encoding="utf-8").strip().startswith("#")


def test_there_is_a_page_for_every_wizard_screen() -> None:
    from ui.store.stage_status import PAGE_NAMES

    numbered = sorted(p.name for p in GUIDE.glob("[0-9][0-9]-*.md"))
    assert len(numbered) == len(PAGE_NAMES)
    for page, name in zip(numbered, PAGE_NAMES, strict=True):
        title = (GUIDE / page).read_text(encoding="utf-8").splitlines()[0].lower()
        assert name.lower() in title, f"{page} should document the {name} screen"


@pytest.mark.parametrize("page", PAGES)
def test_every_local_link_and_image_resolves(page: str) -> None:
    for is_image, target in _links(page):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = (GUIDE / target.split("#")[0]).resolve()
        assert path.exists(), f"{page}: {'image' if is_image else 'link'} {target} is missing"


def test_every_committed_image_is_used_by_a_page() -> None:
    used = {Path(t).name for page in PAGES for img, t in _links(page) if img}
    on_disk = {p.name for p in (GUIDE / "images").glob("*.png")}
    assert on_disk == used, f"unused: {sorted(on_disk - used)}, missing: {sorted(used - on_disk)}"


def test_every_screen_page_shows_at_least_one_screenshot() -> None:
    for page in sorted(GUIDE.glob("[0-9][0-9]-*.md")):
        assert any(img for img, _t in _links(page.name)), f"{page.name} has no screenshot"


def test_readme_links_every_page() -> None:
    linked = {t for _img, t in _links("README.md")}
    for page in PAGES[1:]:
        assert page in linked, f"README does not link {page}"


def test_screenshot_script_and_guide_agree_on_image_names() -> None:
    """Each image the guide shows is one the generator script writes."""
    script = (GUIDE.parents[1] / "scripts" / "generate_guide_screenshots.py").read_text("utf-8")
    written = set(re.findall(r'shot\("([^"]+)"', script))
    shown = {Path(t).stem for page in PAGES for img, t in _links(page) if img}
    extra = sorted(shown - written)
    assert shown <= written, f"guide shows images the script does not write: {extra}"
