# 5 · Metadata (optional)

![Metadata screen](images/05-metadata.png)

Attach experimental information (treatment, date, tank, …) to every row of the output.

1. **Load metadata CSV…**. The first rows are previewed.
2. Match columns to fields. Names like `date`, `condition` or `tank` are matched automatically to
   *Trial date*, *Treatment*, *Group ID*; change any you disagree with, or leave a field on
   `(skip)`.
3. The line under the mapping tells you how many sessions found a row (`1 of 1 sessions matched`)
   and names any that did not.

The `session_id` column must equal the session folder name. Without an *Individual ID* column one
row is matched per session (if several rows match, the first is used and the summary says so).

## Per-animal information (sex, weight, genotype of individual fish)

Give the CSV **one row per animal** and map its animal column (`fish_id`, `animal_id` or any name)
to *Individual ID*. Then:

- **Match animals by** decides how each value is matched to an animal. *Validator label* uses the
  names set in the idtracker.ai Validator (the default labels are `1`, `2`, …) and falls back to the
  0-based position for a session that has none. *Position* always uses the 0-based position (the
  `individual_id` of the exported tables).
- Tick the other columns you want under **Also include these columns**. Columns that are not mapped
  to a field and not ticked are dropped.
- Per-animal values land on every row that has an `individual_id` (the per-frame table and the
  individual metric tables). Values that are the same for all animals of a session (such as
  `treatment`) also go onto the group tables; per-animal values never do.
- The summary lists animals with no row (their cells stay empty), and CSV rows whose animal matches
  nothing.
- **Identity-free sessions** get no per-animal values: their rows are detection slots, not animals.
  Session-level fields still apply.

Pick the right match mode: if your CSV counts animals from 1 and the Validator labels are the default
`1`, `2`, … use *Validator label*; if it counts from 0, use *Position*. A column named like an
engine column (`speed_px_s`, `frame`, `bin_index`, …) is never carried, so it cannot overwrite data.

**Skip metadata** removes the file if you change your mind.
