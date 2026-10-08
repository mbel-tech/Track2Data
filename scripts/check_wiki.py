#!/usr/bin/env python3
"""Check the wiki source in docs/wiki/ before it is published.

The GitHub wiki has no pull requests, no CI and no link checking of its own, and it is a
separate repository from the code -- so a renamed file in this repo silently breaks a wiki
link, and nothing anywhere reports it. This script is that missing check, and
``tests/test_docs/test_wiki.py`` puts it in the CI gate.

It verifies four things:

* every ``[[wiki link]]`` resolves to a page in ``docs/wiki/``;
* every ``https://github.com/<owner>/<repo>/blob/main/...`` link points at a file that
  exists in this repository, and at a heading that exists when it carries an anchor;
* no page is orphaned -- every page is reachable from ``_Sidebar.md``;
* no page uses a relative link, which does not resolve from a wiki page.

    python scripts/check_wiki.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WIKI = REPO / "docs" / "wiki"
SPECIAL = {"_Sidebar", "_Footer", "Home"}

_WIKI_LINK = re.compile(r"\[\[([^\]]+)\]\]")
_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
_BLOB = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/blob/main/([^)\s#]+)(?:#([\w.-]+))?")


def pages() -> dict[str, Path]:
    """Page name (file stem) -> file, for every publishable page."""
    return {p.stem: p for p in sorted(WIKI.glob("*.md")) if p.stem != "README"}


def _target(link: str) -> str:
    """The page a ``[[text|Page-Name]]`` or ``[[Page Name]]`` link points at."""
    return link.split("|")[-1].strip().replace(" ", "-")


def _anchors(text: str) -> set[str]:
    """GitHub-style heading anchors for a Markdown document."""
    out = set()
    for line in text.splitlines():
        m = re.match(r"#{1,6}\s+(.*)", line)
        if m:
            slug = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-")
            out.add(slug)
    return out


def check() -> list[str]:
    """Return a list of problems; empty means the wiki source is publishable."""
    problems: list[str] = []
    known = pages()
    if not known:
        return [f"no wiki pages found in {WIKI.relative_to(REPO)}"]
    for required in ("Home", "_Sidebar", "_Footer"):
        if required not in known:
            problems.append(f"missing {required}.md")

    linked_from_sidebar: set[str] = set()
    for name, path in known.items():
        text = path.read_text(encoding="utf-8")
        where = f"docs/wiki/{path.name}"

        for link in _WIKI_LINK.findall(text):
            target = _target(link)
            if target not in known:
                problems.append(f"{where}: [[{link}]] -> no page {target}.md")
            elif name == "_Sidebar":
                linked_from_sidebar.add(target)

        for repo_path, anchor in _BLOB.findall(text):
            target = REPO / repo_path
            if not target.exists():
                problems.append(f"{where}: links to {repo_path}, which does not exist")
            elif (
                anchor
                and target.suffix == ".md"
                and anchor not in _anchors(target.read_text(encoding="utf-8"))
            ):
                problems.append(f"{where}: {repo_path} has no heading #{anchor}")

        for link in _MD_LINK.findall(text):
            if not link.startswith(("http://", "https://", "#", "mailto:")):
                problems.append(
                    f"{where}: relative link ({link}) does not resolve from a wiki page; "
                    "use an absolute https://github.com/... URL"
                )

    for name in known:
        if name not in SPECIAL and name not in linked_from_sidebar:
            problems.append(f"docs/wiki/{name}.md is not linked from _Sidebar.md")

    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} problem(s)")
        return 1
    print(f"{len(pages())} wiki pages checked, no problems")
    return 0


if __name__ == "__main__":
    sys.exit(main())
