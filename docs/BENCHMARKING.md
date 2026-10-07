# Benchmarking parallel runs

`Engine.run(n_workers=N)` runs sessions in separate processes (D-020). Whether that helps depends
on how long each session takes, how many cores you have and how much memory each worker needs, so
measure on your own machine and data.

```bash
python scripts/benchmark_parallel.py --sessions 8 --frames 108000 --animals 10 \
    --workers 1,2,4,8 --cache off,cold,warm --json bench.json
```

The script writes synthetic idtracker.ai sessions (seeded random walks with a few tracking gaps and
jumps) to a work directory and reuses them between runs. Each (cache mode, worker count) is timed in
a **fresh subprocess**, so the peak memory it reports belongs to that configuration alone.

| Option | Meaning |
|---|---|
| `--cache off\|cold\|warm` | no cache; an empty cache; a cache filled by an untimed run first |
| `--jitter 0.5` | vary session length by up to +/-50 %: exposes load imbalance that equal-length sessions hide |
| `--zones` | add two zones and the zone metrics |
| `--identity-switch` | switch on identity-switch correction (off in the app by default; slow) |
| `--exporters csv_long,feather,excel` | choose exporters (Excel is slow on long sessions) |
| `--sessions-dir DIR` | time real session folders instead of synthetic ones |
| `--repeat N` | repeat each configuration and report the median |

It prints a table (wall time, speed-up and efficiency against the first worker count, peak memory of
the main process and of the largest worker) and a sequential per-stage and per-metric breakdown for
one session. `--json` keeps everything, including the environment (CPU count, platform, versions).
A manual GitHub workflow, *Benchmark (manual)*, runs it on a hosted runner and uploads the JSON; it is
never part of the required checks.

## A data point (not a promise)

4 synthetic sessions, 20,000 frames x 10 animals each, csv_long export, no cache, on a 4-core
sandbox container:

| Workers | Wall time | Speed-up | Efficiency |
|---|---|---|---|
| 1 | 71.2 s | 1.00 | 1.00 |
| 2 | 40.3 s | 1.77 | 0.88 |
| 4 | 22.0 s | 3.24 | 0.81 |

Where the time goes for one such session: metrics 14.8 s (of which the group metrics dominate:
GL-7 2.8 s, GL-13 1.8 s, GL-11 1.5 s, GL-15 1.4 s, GL-4 and GL-6 about 1.3 s each), export 2.9 s,
preprocessing 0.6 s, building the per-frame table 0.3 s. Peak memory was about 270 MB per process.

Read this carefully:

- It is **one run on one small machine** with synthetic data. Real recordings differ (random walks
  cross far more often than real animals, which makes identity-switch correction look slower than
  it would be, and group metrics skip fewer frames).
- It uses **4 sessions on 4 cores**, so 4 workers is the best case; with fewer sessions than workers
  the extra workers are idle (`min(n_workers, n_sessions)` processes are started).
- **Short sessions lose.** Each worker needs about a second to import the engine, so sessions of a few
  hundred frames run slower in parallel (about 3.2 s sequential against 3.3 s with two workers for
  two 2,000-frame sessions).
- The numbers say nothing yet about the 70-session, 100,000-frame case the audit worried about.
  Run the script with `--sessions 8 --frames 108000` (or `--sessions-dir` on real folders) on the
  workstation you will use before choosing a worker count.

Where the time is: the group metrics are Python loops over frames (one KD-tree, hull or distance
matrix per frame), so a vectorised version would help a single-process run as much as parallelism
does. That is not done yet.
