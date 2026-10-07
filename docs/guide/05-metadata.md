# 5 · Metadata (optional)

![Metadata screen](images/05-metadata.png)

Attach experimental information (treatment, date, tank, …) to every row of the output.

1. **Load metadata CSV…**. The first rows are previewed.
2. Match columns to fields. Names like `date`, `condition` or `tank` are matched automatically to
   *Trial date*, *Treatment*, *Group ID*; change any you disagree with, or leave a field on
   `(skip)`.
3. The line under the mapping tells you how many sessions found a row (`1 of 1 sessions matched`)
   and names any that did not.

The `session_id` column must equal the session folder name. One row is matched per session (if
several rows match, the first is used and the summary says so).

> **Per-animal information** (sex, genotype of individual fish) cannot be attached yet: metadata is
> joined per session, so such a value would be copied onto every animal. *Individual ID* is shown
> disabled for that reason. Join those columns yourself in R or Python after exporting.

**Skip metadata** removes the file if you change your mind.
