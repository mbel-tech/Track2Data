# Releasing

Cutting a release is one command. The two integrations it depends on —
Zenodo and PyPI — each need a **one-time manual setup** that cannot be done
from a workflow file, and neither is switched on yet. This document is the
checklist for both.

---

## Cutting a release

1. Bump `track2data/_version.py`. That is the single source of truth;
   `tests/test_version_consistency.py` fails if `pyproject.toml`,
   `CITATION.cff`, the Windows installer or the macOS bundle disagree.
2. Update `CITATION.cff`: `version` and `date-released`.
3. Move the `[Unreleased]` section of `CHANGELOG.md` under the new version
   heading.
4. `git tag vX.Y.Z && git push origin vX.Y.Z`.

The tag triggers `.github/workflows/release.yml`, which builds the three
desktop binaries, runs the determinism gate, publishes the GitHub release
with `SHA256SUMS.txt`, and publishes the engine to PyPI.

---

## One-time setup: PyPI (trusted publishing)

The `pypi` job uses OIDC, so **no API token is stored anywhere** — PyPI
verifies the workflow's identity directly. That is the point: a stored token
in repository secrets is a credential that can leak, and a scientific tool
signing its own releases with one is a worse story than not publishing at
all.

It will fail until a publisher is registered:

1. Create the project on PyPI, or go to an existing project's
   **Manage → Publishing**.
2. Add a **GitHub** trusted publisher:

   | Field | Value |
   |---|---|
   | Owner | `mbel-tech` |
   | Repository | `Track2Data` |
   | Workflow | `release.yml` |
   | Environment | `pypi` |

3. In the repository, create the `pypi` **environment**
   (Settings → Environments). Add a required reviewer if you want a
   human gate before each upload.

**A version can never be re-uploaded to PyPI.** The workflow runs
`twine check` first for that reason: a wheel whose description fails to
render is not fixable after the fact, only superseded.

To rehearse without publishing, point the publish step at TestPyPI
(`repository-url: https://test.pypi.org/legacy/`) and register the
equivalent publisher there.

---

## One-time setup: Zenodo (release DOI)

A DOI is what makes the software citable in a way that resolves in ten
years, and it is the thing reviewers ask for. Zenodo mints one per release
automatically once the integration is on.

1. Sign in to [zenodo.org](https://zenodo.org) with the GitHub account.
2. **Settings → GitHub**, find `mbel-tech/Track2Data`, flip the switch on.
3. Cut a release (or re-publish the existing one). Zenodo archives the tag
   and mints a DOI, reading `CITATION.cff` for the metadata.
4. Zenodo issues **two** DOIs. Use the **concept DOI** — the one that always
   resolves to the newest version — in the README badge and in
   `CITATION.cff`'s `identifiers:`. The per-version DOI belongs in a paper's
   methods section, where the specific version matters.
5. Add the badge to the README, above the title:

   ```markdown
   [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
   ```

6. Fill in `CITATION.cff`:

   ```yaml
   identifiers:
     - type: doi
       value: 10.5281/zenodo.XXXXXXX
       description: Concept DOI, always resolving to the latest release.
   ```

Zenodo only sees releases created **after** the integration is enabled, so
turning it on does not retroactively archive v0.1.0.

---

## Optional: a software paper

The project already meets most of what
[JOSS](https://joss.theoj.org/about#author_guidelines) reviews for: an OSI
licence, a test suite with CI, documented installation and usage, an issue
tracker, and substantial scholarly effort. JOSS is the closest fit for the
scope; *SoftwareX* and *Methods in Ecology and Evolution*'s applications
section are the alternatives, and both want a longer methods treatment.

Whichever route, the submission has to cite idtracker.ai
([Romero-Ferrero et al. 2019](https://doi.org/10.1038/s41592-018-0295-5))
prominently as the upstream tool, and state the version range this reader
was written and tested against.
