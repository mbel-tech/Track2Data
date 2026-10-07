# Security policy

## Reporting a vulnerability

Please report security issues **privately**, not as a public issue:

- Use GitHub's [private vulnerability reporting](https://github.com/mbel-tech/Track2Data/security/advisories/new)
  (Security → Report a vulnerability), or
- email the maintainer at the address on the [GitHub profile](https://github.com/mbel-tech).

Please include what you were doing, what happened, and — if you have one —
a session folder or file that reproduces it. A description is enough; do
not send data you are not free to share.

This is a single-maintainer scientific tool, not a funded product. Expect a
first response within about two weeks. There is no bounty programme.

## What is in scope

Track2Data is a desktop application that reads files a user points it at and
writes derived datasets. The security-relevant surface is therefore mostly
about **untrusted input files**:

| In scope | Notes |
|---|---|
| Code execution from a session folder | The main one. See "Untrusted session folders" below. |
| Code execution from a metadata file (`.csv`/`.xlsx`) | Spreadsheets are parsed, never evaluated; a way around that is a vulnerability. |
| Path traversal when writing exports | Exports must stay under the chosen output directory. |
| A crafted file causing the app to overwrite or delete files outside the export directory | Track2Data never modifies a session folder (FR-IMP-5). |
| Anything in a published release binary | Including the build pipeline that produced it. |

Out of scope: denial of service from a very large or malformed session
(a tracking dataset can legitimately exhaust memory); the absence of code
signing on the first release (documented in `docs/CODE_SIGNING.md`); and
vulnerabilities in idtracker.ai itself, which should go to that project.

## Untrusted session folders

idtracker.ai can write trajectories as pickled `.npy`, and **unpickling
executes arbitrary code from the file**. Track2Data refuses those formats
unless a project explicitly opts in:

- `security.allow_pickle_trajectories` in the project file, **off by default**;
- the GUI asks once per project, naming the folder;
- a folder that also carries an `h5` or `csv` trajectory — which a standard
  idtracker.ai session does — imports normally without ever prompting,
  because the reader falls through to the inert format.

**If you were sent a session folder by someone else, leave the setting off.**
If the folder has only pickled trajectories, ask the sender to re-export it:

```bash
idtrackerai_format <session_folder> --formats h5
```

The blob-layer reader (`readers/idtrackerai/blobs.py`) goes further: it uses
a restricted unpickler that stubs every `idtrackerai.*` class and refuses
anything outside a small numpy allowlist, so no idtracker.ai code runs even
when that path is enabled.

## Supported versions

Only the latest release receives fixes. This project has not yet reached
1.0; there are no maintained release branches.

## Verifying a download

Every release ships `SHA256SUMS.txt` alongside the binaries. Check it before
running past your OS's unsigned-binary warning:

```bash
sha256sum -c SHA256SUMS.txt
```

(`shasum -a 256 -c` on macOS.) Releases are currently unsigned — see
`docs/CODE_SIGNING.md` for why, and for the plan to sign later ones.
