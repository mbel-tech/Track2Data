# 10 · Export

![Export screen](images/10-export.png)

1. Tick the formats you want.

   | Format | Files |
   |---|---|
   | CSV Long | `master_fish_by_frame.csv`, `trial_activity_summary.csv`, `group_dynamics_summary.csv` |
   | CSV Wide | `trial_summary_wide.csv` |
   | Excel | `Track2Data_<project>.xlsx` (one sheet per table) |
   | Feather | `master_fish_by_frame.feather`, `trial_activity_summary.feather` |
   | README | provenance record (always written alongside the others) |

2. **Browse output directory…** or keep the default.
3. **Export**. Metrics and files are produced again, but preprocessing comes from the cache when
   nothing relevant changed.

The **receipt** lists every file with its size and SHA-256. **Copy CLI equivalent** gives the
`track2data run …` command that reproduces this export.

> Very long recordings: Excel limits a sheet to about one million rows, so the per-frame table
> continues on *Fish by Frame 2*, … The CSV and Feather files always hold the whole table.

## Load the data in R or Python

![Code snippets](images/10-export-code.png)

After an export, the panel at the bottom gives ready-to-paste code for the files just written
(R/tidyverse or Python/pandas). **Copy code**, paste, run.

See [Understanding the output files](outputs.md) for what the columns mean.
