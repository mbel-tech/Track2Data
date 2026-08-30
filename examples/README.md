# Example: four fish, two minutes, one command

A complete Track2Data project you can run in about ten seconds, so you can
see the shape of the output before pointing the tool at your own data.

## Run it

```bash
cd examples
track2data run example.t2d.json -o out
```

That is the whole walkthrough. It imports `tiny_session/`, preprocesses it,
computes eight metrics, and writes:

```
out/
├── PROJECT_SUMMARY.md        what ran, and whether these sessions are poolable
├── sessions.csv              fps, duration, group size, calibration
├── codebook.csv              every column: unit, level, metric, DOI
└── tiny_session/
    ├── metrics_long.csv      one row per value  ← start here
    ├── trial_activity_summary.csv
    ├── group_dynamics_summary.csv
    ├── master_fish_by_frame.csv
    ├── manifest.json
    └── README.md
```

Open `metrics_long.csv`. It has one row per measured value, with the unit
attached:

| session_id | individual_id | zone_name | metric_id | column | value | unit |
|---|---|---|---|---|---|---|
| tiny_session | 0 | | IL-1 | path_length_cm | 340.6 | cm |
| tiny_session | 0 | wall | Z-1 | time_pct | 1.0 | fraction (0-1) |

## What is in the session

`tiny_session/` is simulated, not recorded — four fish in a circular arena,
two minutes at 30 fps. It is deliberately **not** random noise: fish 1 and 2
hug the wall, fish 3 and 4 use the middle, everyone freezes occasionally,
and there are short tracking dropouts. Random positions would exercise the
code but teach nothing, because every metric would land on its null value.

So the result is interpretable: `Z-1` shows the two wall-hugging fish at
1.00 in the `wall` zone and the other two at 1.00 in `centre`, which is the
thigmotaxis split that was simulated.

It is written as a **CSV bundle**, not the pickled `.npy` idtracker.ai can
also produce. A `.npy` trajectory is a pickle, and loading one executes
whatever code is in it — so shipping one as a "try this" example would be
handing out an execution vector, and Track2Data would refuse to open it
without an explicit opt-in anyway. See [`SECURITY.md`](../SECURITY.md).

Regenerate or resize it with:

```bash
python examples/make_example_session.py --minutes 10
```

## Then analyse it

Two starter scripts, both reading `metrics_long.csv`:

- [`analysis/analyse.R`](analysis/analyse.R) — `lme4` / `glmmTMB`
- [`analysis/analyse.py`](analysis/analyse.py) — `statsmodels`

Both fit the same model and both stop to explain the same four traps.

---

## Four ways to get this wrong

The tool computes the numbers. These are the mistakes it cannot stop you
making, and they are common enough in this literature to be worth stating
plainly.

**1. Pseudo-replication.** Four fish in one tank are not four independent
observations. They see each other, share water, share a disturbance when
someone walks past. Treating `individual_id` as the unit of replication
inflates your n by the group size and shrinks every p-value accordingly.
Fit `session_id` (or `tank_id`) as a random effect — that is what the
starter scripts do — or aggregate to one value per session before testing.

**2. Unequal tracking duration.** `sessions.csv` carries `duration_s` and
`n_frames` because they differ between sessions more often than people
expect. Path length is a *total*: a session that ran 20% longer produces a
20% larger value for identical behaviour. Use a rate (speed), or include
duration as an offset. The same applies to any count — visits, transitions,
freezing bouts.

**3. Ratios of small counts.** `time_pct`, `frac_*` and Jacobs' D are
bounded ratios, and a ratio computed from few frames is far noisier than one
computed from many — but they look identical in a table. Join
`metrics_long.csv` to **D-11** (`n_frames_used`, `frac_measured`) and
either weight by it or exclude individuals below a coverage threshold you
state in your methods. A fish tracked for 12% of the session should not
carry the same weight as one tracked throughout.

**4. Preprocessing choices are analysis choices.** Smoothing window,
`max_gap_frames`, and whether identity-switch correction ran all change the
numbers — sometimes substantially. They are recorded in `manifest.json` for
exactly this reason. Report them, and if a result is close to your
significance threshold, check whether it survives a different smoothing
window before you believe it.

And one that is not your fault: **`*_pct` columns hold fractions in [0, 1],
not percentages.** `time_pct = 0.42` means 42%. `codebook.csv` states the
real unit for every column; the names are kept only for backward
compatibility.
