# R-parity fixtures — from_choice_pipeline

## Status: external / local-only

The CSV files that belong in this directory are derived from the
choice-experiment R pipeline. They are **not stored in the repository**
because the underlying data are currently pre-publication embargoed.

This directory is `.gitignore`'d (except for this README). Do not
commit raw fixture data here unless redistribution has been explicitly
cleared by the data owner.

---

## Local fixture source

The R pipeline that generates these files lives at:

```
D:\CHOICE R SCRIPTS\choice R pipeline\
```

This path is specific to the maintainer's machine. Collaborators with
access to the same pipeline outputs should copy the relevant CSVs into
this directory following the layout below.

---

## Expected files

| File | Source in R pipeline | Required columns |
|---|---|---|
| `trial_activity_summary.csv` | `output/STEP2_output/…/trial_activity_summary.csv` | `trial_id`, `timepoint`, `total_time_s`, `treatment` |
| `trial_occupancy_long.csv` | `output/STEP2_output/…/trial_occupancy_long.csv` | `trial_id`, `timepoint`, `zone`, `prop_time` |
| `jump_detection_summary.csv` | `output/STEP1_output/…/jump_detection_summary.csv` | `trial_id`, `fish_id`, `n_jumps` |
| `master_fish_by_frame_trial1_t1.csv` | subsample of `output/STEP1_output/…/master_fish_by_frame.csv` | `trial_id`, `frame`, `fish_id` |

`master_fish_by_frame.csv` is ~952 MB; subsample to ≤ 10 MB before
placing it here (filter to `trial_id == 1, timepoint == 1`,
approximately 30 K rows).

---

## Running the local parity check

Once the files above are present, run:

```bash
pytest tests/test_r_parity/test_choice_fixtures_local.py -v -m r_parity_local
```

or with the full r_parity suite:

```bash
pytest tests/test_r_parity/ -v -m r_parity_local
```

These tests are **skipped automatically** in CI and when the fixture
files are absent.

---

## Criteria for committing sanitized fixture subsets

Fixture data may be committed to the repository only when **all** of
the following conditions are satisfied:

1. The associated study has been published or a preprint has been posted.
2. The data owner has explicitly approved redistribution under an
   open-data licence compatible with this project's MIT licence.
3. Each file has been reviewed for personal or sensitive information and
   cleared by the maintainer.
4. Files are ≤ 10 MB each (subsample if larger).

When conditions are met, remove the relevant `.gitignore` exclusion,
convert the `r_parity_local` marker to `r_parity` in
`test_choice_fixtures_local.py`, and update this README.

---

## Tolerance policy

When the parity gate runs, numerical comparisons use the tolerances
defined in `docs/TECHNICAL_SPEC.md` §11.2:

- Continuous metrics: absolute tolerance 1 × 10⁻⁴, relative tolerance 1 × 10⁻³
- Count/integer metrics: exact match
- Zone proportions: absolute tolerance 5 × 10⁻³
