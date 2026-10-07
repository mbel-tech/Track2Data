# Troubleshooting

| You see | Why | What to do |
|---|---|---|
| **Next ▶** is disabled | A required stage is empty or invalid | Hover over Next: the tooltip names the problem. Check the ✗ / ○ badges in the sidebar |
| *"No reader recognised the session folder"* | The folder is not an idtracker.ai output | Pick the session folder itself (the one containing `trajectories/`). Supported: idtracker.ai 6.x output (the legacy v5 layout also works); v4 is not supported yet |
| Session frames / animals show `—` | The folder is still being read | Wait a moment; a failed read is reported in the Run Log |
| `*_cm` columns are empty | No pixels-per-unit scale | Use `*_bl` columns or set a scale in [Calibration](03-calibration.md) |
| ⚠ on *Sessions* | A session is identity-free | Expected for sessions tracked without identities; see [Sessions](02-sessions.md) |
| Individual metrics missing for a session | That session is identity-free | Untick *Identity-free* only if identities really are stable |
| *"N of M sessions matched"* with names listed | Those `session_id` values are not in the metadata CSV | Fix the CSV or the session folder names |
| A zone warning about resolution | Zones were drawn on a different image size | Redraw them on this session, or confirm the sizes really match |
| Path length looks far too large | Jumps or identity swaps | Open [Preview ▸ Trajectories](09-preview.md) with *Raw + processed*; keep *Identity switch correction* off |
| Excel file has *Fish by Frame 2* | The table exceeded Excel's row limit | Use the CSV or Feather file for the complete table |
| Parallel run slower than sequential | Short sessions; each worker takes time to start | Use 1 worker |
| macOS says the app is damaged / Windows SmartScreen blocks it | Releases are not signed yet | See [`docs/CODE_SIGNING.md`](../CODE_SIGNING.md) |

Still stuck? Open the **Run Log** (View ▸ Toggle Run Log), then an issue on GitHub with its text.
