# Before you record

**Applies to:** Track2Data v0.1.0 and later.

Most things Track2Data cannot do for you are decided before the camera starts. This is the
checklist to run through while planning a recording session — each item maps to a problem
that cannot be fixed afterwards.

## The recording

- **Know the frame rate, and keep it constant.** Frame rate scales speed, acceleration and
  path length. Sessions recorded at different rates are not comparable without modelling it,
  and if the tracker's files do not record the rate, Track2Data refuses to guess:
  `READER_OPTION_MISSING` rather than a silently wrong speed.
- **Keep sessions the same length**, or accept that every total (path length, visit counts,
  bout counts) needs a duration offset. `duration_s` and `n_frames` are in `sessions.csv`
  for exactly this reason.
- **One condition per recording.** Treatment, tank and date attach to a session, so a
  session that contains two conditions cannot be split later.
- **Do not change the camera, arena geometry or tracking settings mid-study.** Body length
  and area are defined by idtracker.ai's segmentation parameters, and identity matching
  across sessions needs `resolution_reduction` and `id_image_size` to match; Track2Data
  warns when sessions differ, but the data is already collected by then.
- **Keep the video with the session folder.** If the path idtracker.ai recorded no longer
  exists on the analysis machine, the Video column reads *Not found* and you point at the
  file with **Locate Video…** — metrics do not need it, but the Preview and the calibration
  measurement do.

## The scale

Decide which units you want *before* recording, because one of them needs an object in frame:

- **Centimetres (`*_cm`)** need a pixels-per-unit scale. Put something of known length in
  the frame — a ruler, a calibration card — or measure the arena diameter and record it.
  Without a scale, every `*_cm` column is empty. This is not recoverable from the video
  later unless something of known size is visible in it.
- **Body lengths (`*_bl`)** need only the tracker's body length, which idtracker.ai 6.x
  records; this is the default mode and the right choice when no physical scale exists.
  Note that an idtracker.ai v5 session carries no body length, so those export in pixels.
- **idtracker.ai's own Length Calibration tool** gives a per-session scale. Click carefully:
  Track2Data records how much your clicks disagreed
  (`length_calibration_rel_sd` in `sessions.csv`) and warns above 5 %.

If body size itself differs between your groups, prefer `*_bl` for distances between animals
— body lengths are the comparable quantity.

## Identities

Tracking **with** identities gives you every individual metric and the zone metrics that
follow an animal (Z-3 … Z-9). An identity-free session gives you pooled zone occupancy
(Z-1, Z-2, Z-8) and the nearest-neighbour-matched group metrics, and no per-animal rows.

If your question is about individuals, that is a tracking decision, not an analysis one:
budget the tracking effort for stable identities, and check the ⚠ identity-free flag on the
Sessions screen before you plan the statistics.

## Naming

The **session folder name becomes `session_id`**, and it is the key everything else joins on.

- Give each folder the name you want in the dataset: short, no spaces, consistent across the
  study (`t07_ctrl_d1`, not `Trial 7 (control) copy`).
- The `session_id` column in your metadata CSV must equal the folder name exactly.
- Ids that could escape the output directory are rejected, so avoid path separators and
  leading dots.

## The metadata CSV

Write it while you record, not afterwards. Two shapes, depending on whether the information
is per session or per animal.

**One row per session** — treatment, date, tank:

```csv
session_id,treatment,trial_date,tank
t07_ctrl_d1,control,2026-03-04,A
t08_drug_d1,drug_10mg,2026-03-04,B
```

**One row per animal** — sex, weight, genotype:

```csv
session_id,individual_id,sex,weight_g,genotype
t07_ctrl_d1,1,F,0.42,wt
t07_ctrl_d1,2,M,0.39,wt
t08_drug_d1,1,F,0.45,mut
```

Then on the **Metadata** screen, map your animal column to *Individual ID* and pick how it is
matched: *Validator label* (the names set in the idtracker.ai Validator, by default `1`,
`2`, …) or *Position* (the 0-based `individual_id` of the exported tables). If your CSV
counts animals from 1, use *Validator label*; if from 0, use *Position*. Getting this wrong
silently attaches each animal's data to a different animal, so check the match summary — it
names every session and animal that found no row.

Columns named like engine columns (`speed_px_s`, `frame`, `bin_index`, …) are never carried,
so they cannot overwrite measurements. Unmapped, unticked columns are dropped.

## Zones

If the design involves zones, keep the **arena in the same place in frame** for every
session, and draw the zones once on a frame at that resolution. Zones drawn on a different
image size raise a resolution warning, and re-drawing them per session makes occupancy
numbers incomparable.

## A five-line pre-flight

1. Frame rate known and identical across sessions you will compare.
2. Scale object in frame, or body lengths accepted as the unit.
3. Identities tracked, if the question is about individuals.
4. Session folders named as you want `session_id` to read.
5. Metadata CSV written, with `session_id` matching those names.

Then: [[Install and First Run]] → the
[user guide](https://github.com/mbel-tech/Track2Data/blob/main/docs/guide/USER_GUIDE.md) →
[[Analysis Recipes]].
