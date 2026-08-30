#!/usr/bin/env python3
"""Assemble docs/site/ from the markdown that already exists in the repo.

    python scripts/build_docs_site.py && mkdocs build

The repo's documentation lives where contributors edit it -- next to the
code, in docs/ and at the root. This copies the user-facing subset into the
site tree and generates the metric catalogue, rather than duplicating any of
it: a second hand-maintained copy would go stale, which is the failure mode
this whole audit kept finding.

docs/site/ is generated. It is git-ignored; the workflow builds it fresh.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "docs" / "site"

#: source -> page name in the site
PAGES = {
    ROOT / "README.md": "index.md",
    ROOT / "docs" / "USER_WORKFLOW.md": "workflow.md",
    ROOT / "docs" / "INTEROPERABILITY.md": "interoperability.md",
    ROOT / "SECURITY.md": "security.md",
    ROOT / "CONTRIBUTING.md": "contributing.md",
}

#: Links that point at repo paths have to become links between site pages.
LINK_REWRITES = {
    "docs/USER_WORKFLOW.md": "workflow.md",
    "docs/INTEROPERABILITY.md": "interoperability.md",
    "docs/METRICS_SPEC.md": "metrics.md",
    "SECURITY.md": "security.md",
    "CONTRIBUTING.md": "contributing.md",
}

API_PAGE = """# Engine API

The `track2data` package is importable without Qt, so everything below works
in a script, a notebook or on a cluster node.

::: track2data.api.Engine

::: track2data.core.models

::: track2data.sensitivity
"""


def _rewrite_links(text: str) -> str:
    """Point in-repo links at their site pages, and the rest at GitHub."""
    for repo_path, page in LINK_REWRITES.items():
        text = text.replace(f"]({repo_path})", f"]({page})")
    # Anything still relative refers to a file that is not on the site; send
    # it to the repository rather than leaving a 404.
    return re.sub(
        r"\]\((?!https?:|#|mailto:|[a-z_]+\.md)([^)]+)\)",
        r"](https://github.com/mbel-tech/Track2Data/blob/main/\1)",
        text,
    )


def main() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)

    for source, page in PAGES.items():
        if not source.exists():
            sys.exit(f"missing source page: {source}")
        (SITE / page).write_text(
            _rewrite_links(source.read_text(encoding="utf-8")), encoding="utf-8"
        )
        print(f"  {source.relative_to(ROOT)} -> docs/site/{page}")

    (SITE / "api.md").write_text(API_PAGE, encoding="utf-8")
    print("  generated docs/site/api.md")

    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_metric_catalogue.py"),
         str(SITE / "metrics.md")],
        check=True,
    )


if __name__ == "__main__":
    main()
