# Tier 2 implementation plan: Ctrax and the `trx.mat` family

Tier 2 is Ctrax raw `.mat`, `trx.mat` and FlyTracker (371 recent citations, 70.5 % cumulative).
Gates: G-fragments (what to do with track fragments) and G-JAABA (a real `trx.mat` sample).

| PR | Branch | What | Gate |
|---|---|---|---|
| T2-1 | `feat/reader-ctrax-mat` | Ctrax raw `.mat` | G-fragments (decided below) |
| T2-2 | `feat/reader-trx-mat` | `trx.mat` | G-JAABA: a real sample. **Not started: no sample is pinned.** |

## G-fragments: decided with data in hand

The real Ctrax sample has 193 track ids for at most 17 animals at once. Options were to keep every
id as a slot, or to keep the longest N. The default is to **keep every id as a slot** and mark the
session identity-free by construction (`has_stable_identities = False`, `track_wo_identities = True`);
`top_n` is opt-in. Reasons: dropping tracks silently would discard data without the user choosing
it; the identity-free flag already makes the pipeline refuse per-individual metrics, so 193 slots
cannot be misread as 193 animals; and the choice is recorded (`reader_options`) so a reader of the
export can see it. A file whose slots would not fit in memory (over 1 GiB of positions) is refused
with a request to set `top_n` rather than run out of memory.

**Left for the Tier 2 follow-up.** Group metrics that skip frames with any NaN will see mostly-NaN
slots on a fragment-heavy file. That is a property of the data, not something to hide; a pre-flight
note saying so is a separate piece of work (it needs the advisories to know about fragmentation).

## PR T2-1: Ctrax raw `.mat` (built)

`readers/ctrax_mat.py`, `Peeker.mat_variables` (a header-only listing of a classic MATLAB file's
variables via scipy's `whosmat`), `tests/support/ctrax.py`. Against the real file, `ctrax_raw_mat`
passes every contract case: the positions match the suite's oracle frame by frame, the frame rate is
25.0 from the timestamps, the identity claim is honest, and damaged files are refused cleanly.

Decisions recorded:

- y is flipped with a height the user gives (`height_px`, required); a height smaller than the
  detections is refused (`CTRAX_FRAME_TOO_SHORT`), never clamped.
- The frame rate is read from the file and is not an option. Timestamps that wander by more than
  half a frame are noted on the session, not hidden.
- v7.3 (HDF5) MATLAB files are not claimed: there is no real sample, and D-012 says a container
  format without one is speculation.
- `trx.mat` is explicitly not claimed (a `trx` variable excludes the file) and stays in the
  recognise-only table with a remediation that now says so.

## PR T2-2: `trx.mat` (not started)

Needs G-JAABA: a real `trx.mat` (the JAABA sample data on SourceForge, or one you send). The design
is in `animal_tracking_output_formats.md` section 2.5 (struct `trx`, 1-based frames with an offset,
quarter-axis `a`/`b`, `_mm` twins). Until a sample is pinned it stays recognise-only. FlyTracker's
own `-track.mat` is recognise-only (no public output).
