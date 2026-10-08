# Tier 3 implementation plan: native units, ToxTrac and Anipose

Tier 3 is ToxTrac `Tracking_RealSpace.txt` (218 recent citations) and Anipose pose-3d CSV
(195), with the DeepLabCut 3-D variant. Both report positions with no pixel frame, so the gate
(G-units) comes first and ships with no reader in it.

| PR | Branch | What | Gate |
|---|---|---|---|
| T3-0 | `feat/native-units` | Native units: session fields, export naming, pre-flight rules | G-units |
| T3-1 | `feat/reader-toxtrac` | ToxTrac RealSpace (and its pixel twin when present) | T3-0 |
| T3-2 | `feat/reader-anipose` | Anipose pose-3d CSV, and the DeepLabCut 3-D table | T3-0 |

## PR T3-0: native units (built)

The design is D-032 in `docs/dev/DECISIONS.md`. What was built, in the order it is easiest to
review:

1. `core/units.py`: the pure parts. `relabel_column` / `relabel_frame` rename the pixel family
   (`_px_s2` before `_px_s` before `_px2` before `_px`); `effective_unit` picks `px`, `tu` or the
   confirmed label (a label that collides with another column family is not believed);
   `units_per_cm` knows mm, cm, m, um and nothing else.
2. `Session.coordinate_unit` / `reported_unit` / `has_pixel_frame`; `assemble_session` accepts a
   session with no pixel frame (size optional, stored as 0). Cache schema 3.
3. `exporters/schema.py`: `unit_for_column`, `build_codebook` and `long_table` take the project's
   unit; a pixel-named column in a non-pixel project is "unknown", never "px".
4. `Engine.build_payload` relabels every table once, after the computation; the provenance gains
   `coordinate_unit`, `coordinate_unit_reported` and `coordinate_unit_confirmed`; the README gains a
   "Coordinate unit" row; the run's `codebook.csv` and the sensitivity sweep use the same names.
5. Calibration: body-length and per-session calibration do not apply without pixels; an explicit
   scalar factor means "units per cm"; a confirmed known physical unit gets centimetre columns
   automatically (and "cm" itself gets no second family).
6. `validate()`: one unit per project (`UNIT_MISMATCH` in spirit; the message names the sessions),
   no zones, no fixed pixel defaults left unstated (`MetricParameter.scale_free` exempts the
   numerical-zero tolerances), no scalar calibration of lengths already in centimetres.
7. IL-3 / IL-14 fall back to the extent of the tracked positions when there is no pixel frame and
   no arena zone. The trajectory viewer and the calibration ruler no longer size a canvas from 0.

**Verified by.** A native-unit variant of the toy tracker (`tests/support/toy_reader.py`) drives
every path end to end; the native export is checked column by column against the pixel export of
the same numbers (identical values, `_tu` for `_px`). Pixel projects were compared file by file
against `main` for both calibration modes and both ways a session can name its reader: every CSV
is byte-identical.

**Open questions for the readers.**

- *ToxTrac:* with its pixel twin (`Tracking_<k-1>.txt`) the data is in pixels, and the RealSpace
  scale only rebuilds true pixels, so the reader returns pixels. Without it, native units. The real
  sample's scale is exactly 1.0 with an offset, so its "mm" are pixels: the label must be
  presented as unconfirmed, which is what `reported_unit` plus `tu` does.
- *Anipose:* `x`, `y`, `z` in calibration-board units. 3-D metrics use a chosen 2-D plane (D-031);
  z is kept in `Session.keypoints`.
