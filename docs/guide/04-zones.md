# 4 · Zones (optional)

![Zones list](images/04-zones.png)

Zones are regions of interest (the whole arena, a centre area, a feeder). Zone metrics need at least
one. You can:

- **Import ROIs from Session**: use the polygons drawn in idtracker.ai's validator.
- **Load zones from CSV…**.
- Draw your own, below.

## Drawing zones

![Zone canvas](images/04-zones-canvas.png)

Scroll down to the canvas, which shows the session's background image. Saved zones appear shaded
with their names.

| Tool | How |
|---|---|
| **Points** | Click validator landmarks (blue) in order. **Add Custom Point** lets you click anywhere. |
| **Rectangle** | Drag from one corner to the opposite corner |
| **Circle** | Drag from the centre outwards |
| **Undo point** / Ctrl+Z | Remove the last vertex |
| **Fit** | Fit the whole image in view. The mouse wheel zooms; hold the middle button and drag to pan. |

Custom vertices (orange/green) can be dragged to fine-tune the outline. When the shape looks right
(at least 3 points), give it a **name** and a **level** (`main` or `secondary`) and press
**Save Zone**.

If a zone's source resolution differs from a session's video, a yellow warning appears.
