# 7 · Metrics

![Metrics screen](images/07-metrics.png)

Choose what to compute. Metrics are grouped on three tabs: **Individual** (per animal), **Group**
(across animals) and **Zone** (needs zones; the tab is disabled without them).

- **Search** filters all tabs by name or ID (`speed`, `IL-2`). The line beneath says which tabs
  match.
- **Presets** replace the current selection: *Standard locomotor*, *Thigmotaxis & space use*,
  *Social dynamics*, *All metrics*.
- **ⓘ** opens the definition, formula and literature reference of a metric; **⚙** edits its
  parameters (available on metrics that have any).
- The counter shows how many are selected.
- **Quality threshold** drops frames whose identification probability is below the value.
- **Time bins** splits every session into bins of the chosen length (minutes) and reports each
  metric per bin, with `bin_index`, `bin_start_s` and `bin_end_s` columns. *Whole session* (the
  default) turns it off. Whole-track metrics (tortuosity, home-base stability) stay one row per
  animal with empty bin columns; diagnostics are always whole-session. Thresholds such as the
  freezing speed threshold are fixed from the whole session, so bins are comparable.
- Rows are greyed out for sessions without stable identities; see
  [Sessions](02-sessions.md).

**Diagnostics** (coverage, tracking accuracy, identity stability, …) are always computed and are not
listed here; they appear in [Preview ▸ Diagnostics](09-preview.md).

Every metric is documented in [`docs/METRICS_SPEC.md`](../METRICS_SPEC.md).
