## What and why

<!-- One logical change. Say what problem it solves, not only what it does. -->

## Test plan

<!-- Failing test first, then green. List the commands you ran, e.g.
     pytest tests/ -m "not r_parity and not network"
     ruff check . -->

## Checklist

- [ ] Tests added or updated (written before the fix)
- [ ] `ruff check .` passes
- [ ] Docs updated if behaviour changed (`docs/METRICS_SPEC.md`, `docs/UI_DESIGN.md`, `docs/USER_WORKFLOW.md`)
- [ ] `CHANGELOG.md` entry under `[Unreleased]`; `DECISIONS.md` entry for a non-obvious choice
- [ ] Guide screenshots regenerated if a screen changed (`scripts/generate_guide_screenshots.py`)
