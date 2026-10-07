# 3 · Calibration

Calibration decides which units distances and speeds are reported in.

![Body length calibration](images/03-calibration-body-length.png)

| Mode | Use it when | Reports |
|---|---|---|
| **Body length** (recommended) | You do not have a reliable scale | `*_bl` columns: distances in body lengths. Physical `*_cm` columns stay empty. |
| **Custom (px per unit)** | You know the scale | `*_cm` columns, and `*_bl` columns too whenever the tracker recorded body length |
| **Session calibration** | You used idtracker.ai's *Length Calibration* tool | each session's own ratio; you must confirm the unit |

In Body length mode the screen summarises the body lengths read from your sessions (median and
range, in pixels) so you can sanity-check them.

## Custom scale: measure on the frame

![Custom calibration](images/03-calibration-custom.png)

Pick **Custom**, then **Measure on frame…**. Click both ends of something of known length (a ruler,
the arena diameter), type its real length, and press OK. The pixels-per-unit value is filled in for
you. A third click starts the measurement over.

If a mode is incomplete (no scale, or an unconfirmed unit) the stage shows ✗ and **Next** is
disabled until you fix it.
