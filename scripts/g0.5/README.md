# G0.5 SO101: local robot client, dashboard, and recording tools

This directory is the laptop-side half of the deployment.  It owns COM24 and
the two USB cameras; the GPU server owns the G0.5 checkpoint and inference.
The two machines communicate only through the local end of an SSH tunnel.

## Deployment architecture

```text
SO101 + cameras --(Windows client)--> ws://127.0.0.1:8765
                                         |
                                         | ssh -N -L 8765:127.0.0.1:8765 ...
                                         v
                               GPU policy server on chickadee
```

On the server, copy `start_g05_so101_server.sh` into the GalaxeaVLA checkout
and run it with the checkpoint path.  Its defaults match
`experiments/so100/start_server.sh`: 32 action ticks per recompute and
`torch.compile=true`.  It intentionally listens on `127.0.0.1`, not `0.0.0.0`,
because the SSH tunnel is the only required access path.

On the laptop, first keep the tunnel in a separate PowerShell window:

```powershell
.\scripts\g0.5\open_g05_policy_tunnel.ps1
```

Then start the client.  It is a dry run by default:

```powershell
.\scripts\g0.5\run_g05_so101_client.ps1 -Task "pick up the white block"
```

The Tk dashboard is the default.  It has Start, Stop, Reset cache, Home,
Torque off, Torque on, and Close buttons.  Its fixed camera board is live and
uses the same crop plus `256x256` resize geometry as the policy input; each
recompute card retains the exact frame that was actually sent.  Cards scroll
below the fixed board, without creating a new image window every refresh.

Only after confirming state, camera assignment, and target direction should
live motion be enabled:

```powershell
.\scripts\g0.5\run_g05_so101_client.ps1 `
  -Task "pick up the white block" `
  -EnableMotion
```

Live startup asks for confirmation, then homes to the official G0.5
training-distribution mean unless `-NoHome` is supplied.  **Home is a useful
start pose, not a mechanical calibration or a hard joint limit.**  Torque off
deliberately makes the arm limp so it can be repositioned by hand.

## Reference-aligned defaults

- `ActionFps=15`; `ExpectedActionSteps=32`; `MaxStepDeg=10`.
- Camera `2` is model slot `exterior`; camera `0` is `wrist_right`.
- Exterior removes its rightmost 91 pixels (`round(640/7)`): `640x480 -> 549x480`.
- Wrist is uncropped: `640x480`; both are then independently resized by the
  server to `256x256`.
- Model state/action use G0.5's right-arm 6-D coordinate transform:
  `q_model = [1,-1,1,1,1,1] * q_arm + [0,90,90,0,0,0]`.

`run_g05_so101_client.ps1` exposes every run-specific adjustment, including
camera UVC controls, image crop, home policy, dashboard history, timing log,
and temporary `JointOffsets`/`JointScales`.  The latter are only applied in
RAM to the state/action transform; they never overwrite the LeRobot calibration
JSON files.

Use `-PrintServerResponses` when debugging what the server returned.  Use
`-TimingLog .\outputs\g05_timing.jsonl` to record per-tick client preparation,
round-trip, and total times.  The server must explicitly return additional
timing fields before its internal CUDA sections can be separated from network
round-trip time.

## Environments

Do **not** run `uv sync` on this laptop for live inference.  The dashboard
client intentionally stays in the original, hardware-tested conda environment:

```text
C:\Users\19142\.conda\envs\lerobot\python.exe
```

It is the local editable LeRobot 0.3.4 checkout that knows the seller's SO101
setup.  GPU-side `uv sync` belongs only to the GalaxeaVLA server checkout.

The separate `g05-record-v3` environment is for v3 dataset recording.  See
[README_G05_FINETUNE.md](README_G05_FINETUNE.md) before recording.
