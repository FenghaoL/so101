# G0.5 + SO101 轨迹级 RL / DPO 数据采集工具

这个目录只负责本地采集，不负责训练。训练、DPO/TPO/RL 更新仍然放在服务器端
`GalaxeaVLA` 仓库里做。

本地工具负责：

1. 控制 SO101 follower 和两个 USB 相机；
2. 可选连接 SO101 leader 做 demo / intervention / recovery；
3. 录 LeRobot v3 raw dataset；
4. 额外保存 RL/DPO 需要的 episode label、bucket 信息、事件日志和 timing 日志。

主入口：

```powershell
.\scripts\g0.5\rl\run_g05_rl_collector.ps1
```

## 最短启动命令

只做 autonomous / policy-only 采集：

```powershell
.\scripts\g0.5\rl\run_g05_rl_collector.ps1 `
  -PolicyCkptLabel "g05_ar_sft_pick_white_20260701"
```

如果要打印服务器返回的完整包：

```powershell
.\scripts\g0.5\rl\run_g05_rl_collector.ps1 `
  -PolicyCkptLabel "g05_ar_sft_pick_white_20260701" `
  -PrintServerResponses
```

如果要启用 leader teleop，例如 leader 是 `COM22`：

```powershell
.\scripts\g0.5\rl\run_g05_rl_collector.ps1 `
  -PolicyCkptLabel "g05_ar_sft_pick_white_20260701" `
  -LeaderPort COM22
```

## `PolicyCkptLabel` 是什么？

`-PolicyCkptLabel` 只是写进 metadata 的字符串，不加载模型，也不改变推理结果。

真正用哪个 checkpoint，由服务器端 G0.5 policy server 决定。本地 collector 只连接：

```text
ws://127.0.0.1:8765
```

这个 label 的作用是让以后看数据时知道这批轨迹大概来自哪版模型。

## Bucket 的新语义

这里的 bucket 指的是“物体 / block 的摆放状态标签”，不是机械臂初始姿态类别。

你可以在 dashboard 里手动输入任意 bucket label，例如：

```text
white_block_center_01
white_block_left_02
white_block_near_gripper_A
```

每个 bucket 第一次使用时，工具会自动创建一份 bucket 配置。配置包括：

- bucket label；
- 这个 bucket 使用的 arm 初始姿态；
- 生成 arm 初始姿态时用的 random 值；
- fixed/exterior camera 初始图；
- wrist camera 初始图；
- 成功 episode 数；
- 失败 episode 数；
- bucket metadata 文件路径。

bucket 信息默认保存在：

```text
so101_data\g05_rl_buckets\so101_g05_rl_pick_white_v1\
```

注意：这个 bucket 目录只保存配置、统计和参考图片，不保存 episode 数据。真正的 episode 数据仍然保存在：

```text
so101_data\g05_rl_raw\so101_g05_rl_pick_white_v1\<timestamp>\
```

## New-bucket random +/-deg

dashboard 里有一个输入框：

```text
New-bucket random +/-deg
```

它只在“新 bucket 第一次创建”时生效。

规则是：

```text
arm_init_pose = HOME_ARM + uniform(-random_deg, random_deg) * noise_weights
```

其中 gripper 不加随机噪声。当前参考值：

- `0`：完全使用 home；
- `3`：保守推荐起点；
- `5`：可以更丰富一些，但要先确认桌面安全；
- `8+`：不建议一开始用，容易让起始姿态偏得太多。

如果你输入一个已经存在的 bucket label，工具会复用之前保存的 arm 初始姿态，新的 random
输入不会覆盖旧 bucket。

## Start episode 时发生什么？

点击 `Start episode` 或按 `F5` 后，工具会：

1. 读取 dashboard 里的 bucket label；
2. 如果 bucket 不存在：
   - 根据 `New-bucket random +/-deg` 生成 arm 初始姿态；
   - 保存 bucket 配置；
3. 如果 bucket 已存在：
   - 读取这个 bucket 保存过的 arm 初始姿态；
4. 自动把 follower 移动到该 bucket 的 arm 初始姿态；
5. 移动完成后拍 fixed/exterior 和 wrist 的 bucket 初始参考图；
6. 倒数 2 秒；
7. reset server cache；
8. 开始录 episode。

因此通常不需要先手动点 home。你只需要：

1. 输入 bucket label；
2. 输入 random 值；
3. 摆好物体；
4. 点 `Start episode`。

如果你想提前检查 bucket 对应的姿态和相机图，可以点 `Prepare bucket`。它会创建/读取 bucket、
移动机械臂、保存/显示 bucket 信息，但不会开始录数据。

## Dashboard 按钮

- `Start episode`：准备 bucket，然后开始录制。
- `End SUCCESS`：保存当前 episode，并标记成功。
- `End FAILURE`：保存当前 episode，并标记失败。
- `Discard`：丢弃当前 episode，不保存为 LeRobot episode。
- `Policy mode`：切回 G0.5 policy 控制。会 reset server cache，避免旧动作接管。
- `Teleop mode`：切到 leader 控制。没有 leader 时会被阻止。
- `Re-anchor teleop`：重新设置相对 teleop 锚点。
- `Reset cache`：向服务器发送 `{"__reset__": true}`。
- `Prepare bucket`：只准备当前 bucket，不开始录制。
- `Home`：回到 G0.5 SO101 training-mean home。
- `Torque off`：关闭 follower 力矩，可以手动摆臂。
- `Torque on`：重新开启 follower 力矩。
- `Close`：关闭工具。

## 快捷键

方向键：

- `左方向键`：End SUCCESS
- `右方向键`：End FAILURE
- `上方向键`：Teleop mode
- `下方向键`：Policy mode

额外快捷键：

- `F5`：Start episode
- `Delete`：Discard
- `Ctrl+P`：Policy mode
- `Ctrl+T`：Teleop mode
- `Ctrl+R`：Reset cache

建议录制时让焦点留在 dashboard 主窗口上。没有 active episode 时，按左/右方向键不会保存空数据，只会被忽略。

## 推荐录制流程：模型自主失败/成功

1. 启动服务器端 G0.5 policy server。
2. 本地打开 SSH 端口转发。
3. 运行：

   ```powershell
   .\scripts\g0.5\rl\run_g05_rl_collector.ps1 `
     -PolicyCkptLabel "g05_ar_sft_pick_white_20260701"
   ```

4. 在 dashboard 里输入 prompt，例如：

   ```text
   Pick up the white block.
   ```

5. 输入 bucket label，例如：

   ```text
   white_block_center_01
   ```

6. 如果是新 bucket，`New-bucket random +/-deg` 建议先用 `3`；如果想严格 home，就用 `0`。
7. 摆好物体。
8. 点 `Start episode` 或按 `F5`。
9. 模型运行。
10. 成功则按左方向键；失败则按右方向键。
11. 换物体摆放位置时，输入新的 bucket label。

## 推荐录制流程：人类示教 / 接管

需要先确认 leader 端口，例如：

```powershell
Get-ItemProperty -Path HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM
```

然后启动：

```powershell
.\scripts\g0.5\rl\run_g05_rl_collector.ps1 `
  -PolicyCkptLabel "g05_ar_sft_pick_white_20260701" `
  -LeaderPort COM22
```

示教：

1. `Source` 选 `demo`；
2. `Start mode` 选 `teleop`；
3. 点 `Start episode`；
4. 用 leader 控制 follower；
5. 完成后按左方向键保存成功。

中途接管：

1. `Source` 选 `intervention`；
2. `Start mode` 选 `policy`；
3. 点 `Start episode`；
4. 模型快失败时按上方向键切到 teleop；
5. 人类完成后按左方向键保存成功。

切回模型：

1. 按下方向键或点 `Policy mode`；
2. 工具会 reset cache；
3. 下一次新 observation 到服务器后，模型重新接管。

teleop 默认是相对接管：

```text
follower_target = follower_anchor + (leader_now - leader_anchor)
```

这样可以避免 leader 和 follower 姿态不一致时突然跳动。只有确认两只臂已经对齐时，才考虑
`-AbsoluteTeleop`。

## 保存 episode 为什么慢？

`End SUCCESS` / `End FAILURE` 后，LeRobot 会把当前 episode 的图片编码成视频，并更新 parquet、
metadata 和 stats。你看到的 30-40 秒等待主要来自视频编码。

我没有让多个 `save_episode()` 异步并发运行，因为 LeRobot 的保存过程会修改同一个 dataset
buffer、metadata 和 episode 编号。并发保存的风险是：

- 下一个 episode 和上一个 episode 的 buffer 混在一起；
- metadata episode index 错乱；
- 视频编码还没完成就开始写下一条，导致 dataset 不一致。

稳定优先，所以当前仍然是单条 episode 保存完成后再开始下一条。

dashboard 会显示：

```text
saving ep=<index> elapsed=<seconds>
```

LeRobot 目前没有给出每个视频编码的百分比回调，所以只能显示保存已经耗时多久，不能显示精确进度百分比。

如果你想尝试减少结束后的等待，可以开启 LeRobot 的 streaming encoding：

```powershell
.\scripts\g0.5\rl\run_g05_rl_collector.ps1 `
  -PolicyCkptLabel "g05_ar_sft_pick_white_20260701" `
  -StreamingEncoding `
  -EncoderThreads 2
```

这个模式会在录制过程中边录边编码，结束时通常更快。但它会增加录制过程中的 CPU 负载。建议先录几条短 episode
检查频率和视频是否正常，再决定是否长期使用。

## 输出文件

每次启动会创建一个新的 raw dataset：

```text
so101_data\g05_rl_raw\so101_g05_rl_pick_white_v1\<timestamp>\
```

主要文件：

- LeRobot v3 dataset：视频、parquet、meta；
- `rl_rollout_labels.jsonl`：每条 episode 一行标签；
- `rl_events.jsonl`：按钮、mode switch、cache reset、policy response 等事件；
- `rl_timing.jsonl`：每帧关节角、target、timing；
- `recording_context\g05_rl_collection_contract.json`：采集协议；
- `recording_context\*.json`：当时的 calibration 快照。

bucket 信息默认放在：

```text
so101_data\g05_rl_buckets\so101_g05_rl_pick_white_v1\
```

主要文件：

- `buckets_index.json`：所有 bucket 的总览；
- `buckets\<bucket_label>\bucket.json`：单个 bucket 的配置、成功/失败计数；
- `buckets\<bucket_label>\exterior_outbound.png`；
- `buckets\<bucket_label>\wrist_right_outbound.png`；
- `buckets\<bucket_label>\exterior_server_256.png`；
- `buckets\<bucket_label>\wrist_right_server_256.png`。

## Prepare 到 G0.5 model frame

raw dataset 保存的是本地 LeRobot calibrated degrees。训练前需要 prepare 到 G0.5 model frame：

```powershell
& C:\Users\19142\.conda\envs\g05-record-v3\python.exe `
  .\scripts\g0.5\prepare_g05_so101_dataset.py `
  --source .\so101_data\g05_rl_raw\so101_g05_rl_pick_white_v1\<timestamp> `
  --destination .\so101_data\g05_rl_prepared\so101_g05_rl_pick_white_v1\<timestamp>
```

prepare 会额外写：

```text
rl_rollout_labels_prepared.jsonl
```

它的 `dataset_dir` 会指向 prepared 数据目录，方便服务器训练读取。

## 生成 DPO/TPO pairs

推荐从 prepared 根目录生成：

```powershell
.\scripts\g0.5\rl\build_rl_pairs.ps1 `
  -LabelsRoot .\so101_data\g05_rl_prepared\so101_g05_rl_pick_white_v1 `
  -Output .\so101_data\g05_rl_prepared\so101_g05_rl_pick_white_v1\pairs.jsonl
```

pair 规则：

- 只在相同 `(instruction, init_config_id)` 内配对；
- 这里的 `init_config_id` 现在就是 bucket label；
- `success=true` 且 source 属于 `autonomous, intervention, recovery, demo` 的 episode 可做 chosen；
- `success=false` 且 source 属于 `autonomous` 的 episode 可做 rejected。

## 常见问题

### 报错：`Could not connect on port 'COM22'`

说明 Windows 当前看不到 leader 的串口。只做 autonomous 时不需要 leader，直接默认启动即可。

如果要 teleop，先确认 Windows 里真实端口：

```powershell
Get-ItemProperty -Path HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM
```

然后传：

```powershell
.\scripts\g0.5\rl\run_g05_rl_collector.ps1 -LeaderPort COMxx
```

### `Reset cache` 有什么要求？

本地会向服务器发送：

```json
{"__reset__": true}
```

服务器应该返回：

```json
{"__reset__": true}
```

如果服务器端没有实现这个 handler，`Reset cache`、切回 policy、开始/结束 episode 时可能报错。

### camera 图像标准

fixed camera：

```text
原始 640x480
裁掉右侧 160px
保存 / 显示 / 发给服务器：480x480
```

wrist camera 默认不裁剪，仍是 640x480；发给服务器前会 resize 到 256x256。
