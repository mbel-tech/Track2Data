# Formats and Interoperability

Track2Data reads idtracker.ai, DeepLabCut, SLEAP (analysis HDF5), Ctrax (raw `.mat`) and `trx.mat` output; [[Compatibility]] has the status of each (pre-1.0, see the [changelog](https://github.com/mbel-tech/Track2Data/blob/main/CHANGELOG.md)).

## Headless commands

```bash
track2data list-readers          # what can be read, and which options each reader needs
track2data scan ROOT             # which software wrote a folder, with the evidence
track2data add PROJECT ROOT      # suggest, amend (--reader, --option fps=30), confirm, then add
```

A required option the files do not record (for example frame rate) is never defaulted; the reader reports `READER_OPTION_MISSING` instead.

Trackers whose files record no scale accept an optional `px_per_unit` (pixels per cm), which Session calibration then uses:

```bash
track2data add PROJECT ROOT --reader deeplabcut --option fps=30 --option width_px=1920 --option height_px=1080 --option px_per_unit=14.2
```

## idtracker.ai

- [Interoperability overview](https://github.com/mbel-tech/Track2Data/blob/main/docs/INTEROPERABILITY.md)
- [idtracker.ai format analysis](https://github.com/mbel-tech/Track2Data/blob/main/docs/IDTRACKERAI_FORMAT_ANALYSIS.md)
- [idtracker.ai output structure](https://github.com/mbel-tech/Track2Data/blob/main/docs/idtrackerai_output_structure.md)
- [idtracker.ai v4 samples](https://github.com/mbel-tech/Track2Data/blob/main/docs/IDTRACKERAI_V4_SAMPLES.md)

## Other trackers

- [Tracker formats: research notes and rollout](https://github.com/mbel-tech/Track2Data/blob/main/docs/tracker-formats/README.md)
- [Tracker import design](https://github.com/mbel-tech/Track2Data/blob/main/docs/tracker-formats/2026-10-07-tracker-import-design.md)

## Metrics

- [Metrics specification](https://github.com/mbel-tech/Track2Data/blob/main/docs/METRICS_SPEC.md) and [references (CSV)](https://github.com/mbel-tech/Track2Data/blob/main/docs/METRIC_REFERENCES.csv)
