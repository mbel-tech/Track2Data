# Reanalysing after a metric fix

**Applies to:** Track2Data v0.1.0 and later, while the project is pre-1.0.

Metric definitions are still being corrected. If you exported a dataset weeks ago, the
question is whether the numbers in your draft are the numbers this version would produce.
This is how to find out without re-doing the analysis blind.

## 1. Establish what produced your export

Every run writes `manifest.json` next to the data. Read `run_metadata`:

```bash
python -c "import json;m=json.load(open('out/my_session/manifest.json'))['run_metadata'];print(m['app_version'], m['project_hash'], m['generated_at']);print(m['metrics_computed'])"
```

- `app_version` — the Track2Data version that computed the values.
- `project_hash` — the settings that produced them. Two runs with the same hash used the
  same configuration.
- `metrics_computed` — which metric ids are in this export.
- `session_provenance` — which reader read the folder, and with which options.

The per-session `README.md` holds the same facts in prose, plus the SHA-256 of each output
file, so you can confirm a file has not been edited since the run.

## 2. Read the changelog between that version and now

In [`CHANGELOG.md`](https://github.com/mbel-tech/Track2Data/blob/main/CHANGELOG.md), work
forward from your `app_version`. Three kinds of entry matter, in descending order:

1. **A changed definition or a corrected formula** — the values change. Re-export.
2. **A changed output shape** — new or renamed columns, or rows that are now pooled rather
   than per animal. Your script may still run and silently analyse something else.
3. **New metrics, UI changes, performance work** — your existing values are unaffected.

Entries that changed values in the v0.1.0 era, as examples of what to look for: `*_bl`
columns were always NaN and now compute as `value_px / body_length_px` (D-015); the nine
zone metrics emitted per-slot rows on identity-free sessions, and Z-1, Z-2 and Z-8 are now
pooled without `individual_id` while Z-3 … Z-9 require identity (D-016); per-animal
metadata is now matched per animal instead of being copied onto every animal (D-025).

Metric-level detail lives in
[`docs/METRICS_SPEC.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/METRICS_SPEC.md),
and the reasoning behind a change in
[`docs/dev/DECISIONS.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/dev/DECISIONS.md).

## 3. Re-run the same project and diff the values

Re-use the project file, not a freshly configured one — otherwise you are comparing
settings as well as code.

```bash
track2data run my_experiment.t2d.json -o out_new/
```

Then compare the long tables on their identifying columns:

```python
import pandas as pd
from pathlib import Path

KEYS = ["session_id", "individual_id", "zone_name", "metric_id", "column"]

def load(run_dir):
    frames = [pd.read_csv(f) for f in sorted(Path(run_dir).rglob("metrics_long.csv"))]
    df = pd.concat(frames, ignore_index=True)
    # Empty individual_id / zone_name are meaningful keys (pooled or group rows),
    # and NaN never matches NaN in a merge.
    df[KEYS] = df[KEYS].fillna("")
    return df

old, new = load("out"), load("out_new")

cmp = old.merge(new, on=KEYS, how="outer", suffixes=("_old", "_new"), indicator=True)
print(cmp["_merge"].value_counts())                      # rows that appeared or vanished
changed = cmp[cmp["_merge"] == "both"].copy()
changed["abs_diff"] = (changed.value_new - changed.value_old).abs()
changed["rel_diff"] = changed.abs_diff / changed.value_old.abs().replace(0, pd.NA)
moved = changed[changed.rel_diff > 1e-6]
print(moved.groupby("metric_id").rel_diff.agg(["count", "median", "max"]))
```

Three outcomes:

- **No rows moved** — your published numbers are current. Record both versions and move on.
- **Rows appeared or vanished** (`left_only` / `right_only`) — the output *shape* changed.
  Check whether your script was aggregating over rows that no longer exist, or missing rows
  that now do.
- **Values moved** — read the changelog entry for those `metric_id`s and decide whether the
  old or the new definition is the one your methods section describes.

A run reads from the session cache when nothing relevant changed, and the cache key
includes the reader and its options, so a re-run after an upgrade recomputes what it must.

## 4. Decide, and say which version you used

A corrected metric is not an inconvenience to hide. If the correction changes a reported
value:

- Re-export, re-run the analysis, and report the version that produced the final numbers
  (`app_version` and `project_hash`, both in `manifest.json`).
- If the conclusion changes, say which definition each version used — the changelog and
  `DECISIONS.md` give you citable wording.
- If a value sits close to your significance threshold, also check it survives a different
  preprocessing grid before you rely on it:
  `track2data sensitivity my_experiment.t2d.json -o sensitivity/`.

## 5. Protect the next dataset

- Pin the version you publish with, and keep the installer or the tag.
- Keep `manifest.json` and the per-session `README.md` with the data, not just the CSVs.
- Keep the `.t2d.json` project file under version control with your analysis scripts: it is
  the only thing that makes a re-run comparable.
- Re-export a whole study with one version rather than mixing exports from two.

Related: [[Known Issues]] · [[Statistics and Pseudoreplication]]
