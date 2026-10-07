# Critical issues audit - verified status

Reconciled against the code at commit `0b9b860`. An external audit listed 15 issues; this
file records which are real, which are deliberate deferrals, and where they are tracked.
Paths are repo-relative. Updated as the fixes land (see `CHANGELOG.md` and `DECISIONS.md`).

| ID | Area | Sev | Status at 0b9b860 | Notes |
|---|---|:-:|---|---|
| SCI-01 | Science | P0 | **Open** (audit wrongly said fixed) | `calibration/bodylength.py` stores px in `body_length_cm` and leaves `px_per_cm=None`; `*_bl` outputs sit under `if px_per_cm is not None` (`metrics/individual.py`, `metrics/group.py`) so they are always NaN. Tests build sessions with both values, which no real path produces. |
| SCI-02 | Science | P1 | **Fixed** (D-016) | All nine Z-* metrics emit per-slot rows on identity-free sessions (`metrics/zone.py`, `docs/ROADMAP.md` "Deferred: identity-free zone metrics"). |
| SCI-03 | Science | P2 | Open, by design (D-010) | Metadata join is session-level only. |
| PERF-01 | Engine | P1 | Open, deferred (D-013/D-014) | `Engine.run` forces `n_workers=1`; `core/parallel.py` unused. |
| PERF-02 | Engine | P1 | Open, deferred (D-013) | `CacheStore` stores flat DataFrames; `PreprocessedSession` needs a serialisation design. |
| PERF-03 | Engine | P2 | Open | GUI probes sessions with a full `read_session`. |
| PERF-04 | Engine | P2 | Open | `exporters/csv_long.py` copies and sorts the per-frame table before one `to_csv`. |
| GUI-01 | UX | P1 | Open | Apply buttons on Calibration, Preprocessing, Metadata mapping, Metrics; no on-leave hook. |
| GUI-02 | UX | P1 | Open | No trajectory plotting; no plotting dependency. |
| GUI-03 | UX | P2 | Open | `WizardSidebar.mark_complete` (`app/navigation.py`) is never called; Next is ungated. |
| GUI-04 | UX | P2 | Open | Zone canvas has no edges, fill, saved-zone display, zoom/pan or undo. |
| GUI-05 | UX | P2 | Open | Cancellation is only checked at stage boundaries; probes are not cancellable. |
| ENG-01 | Engine/GUI | P2 | Open | `PreprocessingScreen._apply` rebuilds `PreprocessConfig`, resetting `identity_switch` and other unexposed fields. |
| ENG-02 | Engine | P2 | Open, deferred (D-012) | v4 reader is a stub; no v4 sample data. |
| DIST-01 | Distribution | P2 | Open, blocked | Signing is wired in `release.yml` but needs certificates and a published release (`docs/CODE_SIGNING.md`). |

Corrections to the original audit: `ui/widgets/wizard_nav.py` and `metrics/group_m2.py` do not
exist (the sidebar is `app/navigation.py`, GroupSpread is in `metrics/group.py`); the audit's
`BodyLengthArray` was never merged.
