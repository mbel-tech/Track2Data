# IL-11 turn-bias sign check (to do with a real clip)

`left_right_turn_bias` is `mean(sign(wrap(θ_t − θ_prev)))`, with `θ = atan2(vy, vx)` computed from image coordinates (x right, y **down**). In that frame an increasing heading turns **clockwise on the screen**, so a positive bias means a net clockwise (right) turn bias for a viewer looking at the video. The metric's code was not changed (decision D-054) because no real clip was available to confirm what is meant by "left" for the manuscript.

## What to check

1. Pick a clip where one animal clearly swims a circle anticlockwise on screen (or draw a track by hand with a known direction).
2. Run IL-11 on it and read `left_right_turn_bias`.
3. Expected with the present code: **negative** for an anticlockwise circle, positive for a clockwise one.
4. If "positive = left" is the wanted convention, flip the sign in `CircularHeadingStats` (`track2data/metrics/individual.py`), update `tests/test_metrics/test_metric_edge_cases.py` (the test that pins the sign), and re-run the analyses that report this column (see the wiki page *Reanalysing After a Metric Fix*).
5. Also check that the camera is not mirrored or viewed from below; the sign is relative to the video image, not to the animal.
