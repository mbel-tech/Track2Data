# Wiki source

The published GitHub wiki (<https://github.com/mbel-tech/Track2Data/wiki>) is generated from
this directory. Edit here, by pull request; do not edit pages in the wiki UI — the next
publish would overwrite them.

- `.github/workflows/wiki.yml` pushes every `*.md` here to the wiki repository on merge to
  `main`. Filenames become page names (`Known-Issues.md` → "Known Issues"), and `_Sidebar.md`
  / `_Footer.md` apply to every page.
- `scripts/check_wiki.py` (run by `tests/test_docs/test_wiki.py`, so it is part of the CI
  gate) checks that every `[[wiki link]]` resolves to a page here, that every repository link
  points at a file and heading that exist, that no page is orphaned from the sidebar, and
  that no page uses a relative link — relative paths do not resolve from a wiki page.
- Tick **Settings → Features → Wikis → Restrict editing to collaborators only**, so the
  published copy cannot diverge from this directory.

## What belongs here, and what does not

The wiki holds release-independent, question-driven material: how to get from an export to a
statistical result, vocabulary, what is currently in flux, what runs on what. It is not
versioned with a tag, so anything that must be true of a *specific* release belongs in the
repository instead — the user guide, `METRICS_SPEC.md`, the format analyses, `SECURITY.md`,
`CONTRIBUTING.md`.

Pages that only point at repository documentation (`User-Guide.md`, `Developer-Docs.md`)
stay one screen long and duplicate nothing. Pages that could age carry an
`**Applies to:**` line under the title.
