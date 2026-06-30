# G0.5 SO101 RL data collection

This folder is for local data collection only.  Training still belongs on the
server-side GalaxeaVLA checkout.

Start the collector:

```powershell
.\scripts\g0.5\rl\run_g05_rl_collector.ps1
```

The dashboard records LeRobot v3 raw data plus sidecar RL labels:

- `rl_rollout_labels.jsonl`: one row per saved episode, with `success`,
  `source`, `init_config_id`, and human-control intervals.
- `rl_events.jsonl`: operator actions, cache resets, policy recomputes.
- `rl_timing.jsonl`: per-frame timing and executed targets.

Control modes:

- `policy`: execute the G0.5 server's `action.right_arm`.
- `teleop`: ignore policy actions and use the leader arm.  By default this is
  relative takeover, so switching modes does not jump the follower to the
  leader's absolute pose.

After collection, prepare raw LeRobot runs with the existing
`scripts\g0.5\prepare_g05_so101_dataset.py`.  The prepare step leaves the raw
RL label untouched and writes `rl_rollout_labels_prepared.jsonl` beside the
prepared dataset, with `dataset_dir` pointing at the prepared model-frame copy.

Then build DPO pairs from successful and failed episodes in the same
instruction/bucket:

```powershell
.\scripts\g0.5\rl\build_rl_pairs.ps1 `
  -LabelsRoot .\so101_data\g05_rl_prepared\so101_g05_rl_pick_white_v1 `
  -Output .\so101_data\g05_rl_prepared\so101_g05_rl_pick_white_v1\pairs.jsonl
```

If you build pairs before preparation, point `-LabelsRoot` at the raw run/group
directory instead.  The pair builder automatically prefers
`rl_rollout_labels_prepared.jsonl` over raw `rl_rollout_labels.jsonl` when both
exist in the same directory.
