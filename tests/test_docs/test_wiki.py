"""The wiki source must be publishable: no broken links, no orphan pages.

The published wiki is a separate repository with no CI of its own, so these checks run here
instead. The logic lives in scripts/check_wiki.py, which is also runnable by hand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_wiki.py"


def _checker():
    spec = importlib.util.spec_from_file_location("check_wiki", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_wiki"] = module
    spec.loader.exec_module(module)
    return module


def test_wiki_source_has_no_problems() -> None:
    problems = _checker().check()
    assert not problems, "\n".join(problems)


def test_every_page_that_can_age_says_which_version_it_describes() -> None:
    """Pointer pages are exempt; pages with their own content are not.

    The wiki is not versioned with a tag, so a page stating defaults, column names or CLI
    behaviour has to say what it describes.
    """
    checker = _checker()
    exempt = {"Home", "_Sidebar", "_Footer", "User-Guide", "Developer-Docs",
              "FAQ-and-Troubleshooting", "Formats-and-Interoperability", "Known-Issues"}
    missing = [
        name
        for name, path in checker.pages().items()
        if name not in exempt and "**Applies to:**" not in path.read_text(encoding="utf-8")
    ]
    assert not missing, f"no 'Applies to:' line: {missing}"


@pytest.mark.parametrize("required", ["Home", "_Sidebar", "_Footer"])
def test_special_pages_exist(required: str) -> None:
    assert required in _checker().pages()
