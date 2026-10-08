# Citing Track2Data

**Applies to:** Track2Data v0.1.0 (released 2026-08-24, MIT).

Cite three things, in descending order of how often they are forgotten: the tracker, this
tool, and the works behind the metrics you actually report.

## 1. idtracker.ai

Track2Data does not track anything — it reads idtracker.ai output. The tracker is the
measurement instrument and must be cited:

> Romero-Ferrero, F., Bergomi, M. G., Hinz, R. C., Heras, F. J. H., & de Polavieja, G. G.
> (2019). idtracker.ai: tracking all individuals in small or large collectives of unmarked
> animals. *Nature Methods*, 16, 179–182. https://doi.org/10.1038/s41592-018-0295-5

```bibtex
@article{romeroferrero2019,
  author  = {Romero-Ferrero, F. and Bergomi, M. G. and Hinz, R. C. and Heras, F. J. H. and de Polavieja, G. G.},
  title   = {idtracker.ai: tracking all individuals in small or large collectives of unmarked animals},
  year    = {2019},
  journal = {Nature Methods},
  volume  = {16},
  pages   = {179--182},
  doi     = {10.1038/s41592-018-0295-5}
}
```

## 2. Track2Data

GitHub's **Cite this repository** button (top right of the repository page) reads
[`CITATION.cff`](https://github.com/mbel-tech/Track2Data/blob/main/CITATION.cff) and will
give you APA or BibTeX for the current release. The equivalent, by hand:

```bibtex
@software{bellio_track2data,
  author  = {Bellio, Martina},
  title   = {Track2Data: analysis-ready behavioural datasets from idtracker.ai output},
  year    = {2026},
  version = {0.1.0},
  license = {MIT},
  url     = {https://github.com/mbel-tech/Track2Data}
}
```

**There is no release DOI yet.** The Zenodo integration is prepared but not switched on, so
until it is, cite the *version and commit you actually ran* — both are recorded in every
export's `manifest.json` under `run_metadata` (`app_version`, `project_hash`). Replace
`version` above with the version you ran, and say so in the methods rather than citing
"latest".

## 3. The metrics you report

Every metric carries a citation to the work that defines it, and those are the citations a
reviewer of a behavioural paper will expect to see — not a citation to the software that
computed them. Two machine-readable sources ship with the repository:

- [`docs/METRIC_REFERENCES.csv`](https://github.com/mbel-tech/Track2Data/blob/main/docs/METRIC_REFERENCES.csv)
  — one row per metric: `metric_id`, `metric_name`, `reference`, `doi`,
  `supporting_references`.
- [`docs/references.bib`](https://github.com/mbel-tech/Track2Data/blob/main/docs/references.bib)
  — the same works as BibTeX, ready for your reference manager.

The `codebook.csv` in your own export carries the DOI for each column you exported, so the
citation list for a specific analysis can be generated from the data:

```python
import pandas as pd
cb = pd.read_csv("out/codebook.csv")
print(cb.loc[cb.doi.notna(), ["column", "metric_id", "doi"]].drop_duplicates())
```

Where a metric has no single originating work, the reference says so in plain words
("Standard kinematics; no single originating work") rather than inventing one — do not
convert those into a citation.

## What to put in the methods section

Citations identify the tool; these identify the *run*, and without them the numbers are not
reproducible:

- Track2Data `app_version` and `project_hash` (`manifest.json` → `run_metadata`).
- idtracker.ai version used for tracking.
- Calibration mode, and whether values are in cm, body lengths or pixels.
- Preprocessing settings: smoothing method and window, `max_gap_frames`, whether
  identity-switch correction ran.
- The bout criterion actually applied, for bout metrics (`bout_criterion_effective`,
  `min_bout_frames_used`).
- Your coverage threshold and how many individuals it excluded.
- The metric ids you report, and your unit of replication.

The full checklist, with the reasoning, is at the end of
[[Statistics and Pseudoreplication]].
