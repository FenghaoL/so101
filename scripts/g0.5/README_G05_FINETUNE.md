# Recording and preparing SO101 data for G0.5 fine-tuning

## The three representations

1. `record_g05_so101.ps1` records a **raw LeRobot v3** dataset in the local,
   calibrated degree frame.  It keeps original `640x480` videos and snapshots
   the follower/leader calibration JSON files next to each run.
2. `prepare_g05_so101_dataset.py` creates a new sibling dataset; it never
   edits the raw recording.  It maps both `observation.state` and `action` to
   G0.5's SO100 model frame:

   ```text
   q_model = [1,-1,1,1,1,1] * q_arm + [0,90,90,0,0,0]
   ```

3. The GPU training adapter crops only the exterior image right by 91 pixels
   (`round(640/7)`) while loading.  It maps `fixed -> exterior`, `wrist -> wrist_right`, and
   pads `wrist_left` black.  This exactly matches the live client.

Do not give raw data directly to G0.5 fine-tuning, and never send prepared
model-frame angles directly to physical motors.

## Recording environment

Recording uses the separate environment already created at:

```text
C:\Users\19142\.conda\envs\g05-record-v3
```

It has Python 3.12 and `lerobot==0.5.1`, which writes LeRobot `v3.0` datasets
and registers `so101_follower` / `so101_leader`.  The original local `lerobot`
environment is intentionally kept unchanged for the live dashboard client.

The current 0.5.1 OpenCV config no longer exposes camera exposure fields.
`record_g05_with_camera_controls.py` handles this explicitly: it patches the
recorder process before cameras start streaming, applies the requested UVC
`auto_exposure` then `exposure` to the recorder's own handles, and logs both
the requested and read-back values.  If a camera driver rejects a property,
the log says so; it is not silently treated as successful.

## First recording: one-episode smoke test

Close the live policy dashboard first; cameras cannot be opened by it and the
recorder at the same time.  Then run:

```powershell
.\scripts\g0.5\record_g05_so101.ps1 `
  -Task "pick up the white block" `
  -Episodes 1 `
  -DisplayData
```

The first episode is only a schema and visual test.  Inspect the saved fixed
and wrist videos before collecting demonstrations.  Use the same table layout,
camera mounting, crop, and exposure settings that will be used for deployment.
Both follower and leader are explicitly configured in **degrees**; never alter
only one side.

The recorder explicitly loads the existing calibration files under
`.../calibration/robots/so101_follower` and
`.../calibration/teleoperators/so101_leader`.  This is important because the
LeRobot 0.5.1 generic SO implementation otherwise searches different
`so_follower` / `so_leader` directories and may try to recalibrate.  If it
reports a mismatch, press Enter only to restore the listed existing SO101
calibration to the motors; do **not** type `c` to create a new calibration.

The recorder preserves incomplete data rather than deleting it if an error
occurs.  Pick a new `-RunName` instead of overwriting a prior run.

## Prepare a successful recording

At the end of recording, the launcher runs a read-only schema check.  Make the
prepared copy only after that passes:

```powershell
$Py = "C:\Users\19142\.conda\envs\g05-record-v3\python.exe"
$Raw = "D:\workspace\Manipulation\so101\so101_data\g05_raw\so101_g05_v3\pick_up_the_white_block\<run>"

& $Py .\scripts\g0.5\prepare_g05_so101_dataset.py `
  --source $Raw `
  --destination "${Raw}_g05_model_frame"
```

Unchanged videos and metadata are hard-linked where Windows permits it (or
copied as a safe fallback); episode parquet files are transformed.  The source
directory is never changed, and an existing destination is refused.

## GPU fine-tuning assets

The four files under [server_assets](server_assets) are a copy-ready patch for
the GalaxeaVLA GPU checkout.  Read its README, copy them to the listed paths,
then run the one-step dry run there before a real fine-tune.  The task config
computes fresh normalisation statistics for this data; do not overwrite or
reuse the zero-shot checkpoint's SO100 statistics.
