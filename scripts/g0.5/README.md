# G0.5 SO-101 local deployment files

This folder is the Windows robot-side entry point.  It talks to a G0.5 policy
server through a localhost SSH tunnel.  The GPU model and checkpoint remain on
the server.

## Local environment

Use the existing `lerobot` conda environment.  It already supplies every local
dependency required by `g05_so101_policy_client.py`:

- Python 3.10
- `lerobot==0.3.4` and Feetech support for the SO-101 follower
- `numpy`, `opencv-python`, `websockets`, and `msgpack`

Do **not** run `uv sync` on the laptop for this client.  `uv sync` belongs to
the GPU server's GalaxeaVLA checkout, where it installs model and CUDA
dependencies.

## Normal order

1. On the GPU server, start `scripts/serve_policy.py` with the G0.5 SO-101
   checkpoint, loopback host `127.0.0.1`, and port `8765`.  The included shell
   script is a copy template for that server checkout.
2. In one local PowerShell window, run `./open_g05_policy_tunnel.ps1`.
3. In another local PowerShell window, run the local client in dry-run mode:

   ```powershell
   .\run_g05_so101_client.ps1 -Task "pick up the red block"
   ```

4. Verify the two camera views, state logs, and server responses.  Only then
   add `-EnableMotion` for live control.

To inspect the exact first RGB images sent through WebSocket, without relying
on an OpenCV GUI window, add a dump directory during a dry run:

```powershell
.\run_g05_so101_client.ps1 -Task "pick up the white block" `
  -DumpObservationDir .\outputs\g05_input_check
```

By default the client treats the two physical views separately:

- exterior: removes the rightmost 160 pixels, `640x480 -> 480x480 -> 256x256`;
- wrist_right: preserves the full frame, `640x480 -> 256x256`.

The server stretches each source image independently to `256x256`. The dump
contains the actual outbound images and their server-resize previews. Adjust
`-FixedCropRightPx` or `-WristCropRightPx` when needed.

The runner also passes `-FixedExposure` and `-WristExposure` directly to the
OpenCV/DirectShow camera configuration. Both default to `-5.0`, matching the
previous pi0.5 setup; use the exposure probe before choosing another value.

Camera assignments match the existing pi0.5 setup:

- fixed camera index `2` -> G0.5 `exterior`
- wrist camera index `0` -> G0.5 `wrist_right`
- missing `wrist_left` -> a zero RGB image, as expected by the SO-101 model

Use `lerobot-find-cameras opencv` before a session if USB camera ordering may
have changed.

The launcher defaults to one warmup inference, a 120-second timeout, no OpenCV
display window, a 2-degree action bound, and only 20 policy steps. Examples:

```powershell
# Longer dry run; still sends no model action to the robot.
.\run_g05_so101_client.ps1 -Task "pick up the white block" -MaxSteps 60

# Short live test, only after dry-run validation.
.\run_g05_so101_client.ps1 -Task "pick up the white block" -EnableMotion
```
