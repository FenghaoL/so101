# G0.5 square-camera demonstration batches

Each PowerShell file starts one 30-episode collection with no command-line
parameters. They all use the same contract:

- task-specific directory below `so101_data/g05_raw/so101_g05_square_v1`;
- fixed camera: native `640x480` capture, right-cropped and stored as `480x480`;
- wrist camera: stored as `640x480`;
- dataset/control frequency: 15 Hz.

Run exactly one batch at a time, for example:

```powershell
.\scripts\g0.5\record_tasks\01_pick_up_white_block.ps1
```

Keyboard controls are inherited from `record_g05_so101.ps1`: Right Arrow saves
the current episode early, Left Arrow discards/re-records it, and Escape stops
the batch. The batch launchers intentionally leave `-DisplayData` off: a Rerun
viewer is unnecessary for a 30-episode batch and can retain file handles after
the run. The saved fixed-camera video is square regardless of this option.
