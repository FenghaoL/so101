[CmdletBinding()]
param(
  [string]$Task = "Pick up the white block.",
  [string]$DatasetBaseDir = "D:\workspace\Manipulation\so101\so101_data\g05_rl_raw",
  [string]$DatasetGroup = "so101_g05_rl_pick_white_v1",
  [string]$BucketRoot = "",
  [string]$RunName = "",
  [string]$DatasetNamespace = "fenghao",
  [string]$PolicyCkptLabel = "",

  [int]$PolicyPort = 8765,
  [double]$ActionFps = 15.0,
  [int]$DatasetFps = 15,
  [int]$ExpectedActionSteps = 32,
  [double]$MaxStepDeg = 10.0,
  [double]$TimeoutS = 120.0,

  [string]$FollowerPort = "COM24",
  # Leave empty for autonomous/policy-only collection.  Set to COMxx when you
  # want demo/intervention/recovery teleop from a leader arm.
  [string]$LeaderPort = "",
  [string]$FollowerId = "fenghao_so101_follower",
  [string]$LeaderId = "fenghao_so101_leader",
  [string]$FollowerCalibrationDir = "$env:USERPROFILE\.cache\huggingface\lerobot\calibration\robots\so101_follower",
  [string]$LeaderCalibrationDir = "$env:USERPROFILE\.cache\huggingface\lerobot\calibration\teleoperators\so101_leader",

  [int]$FixedCameraIndex = 2,
  [int]$WristCameraIndex = 0,
  [int]$FixedCropRightPx = 160,
  [int]$WristCropRightPx = 0,
  [int]$CameraFps = 30,
  [double]$FixedAutoExposure = 0.25,
  [double]$WristAutoExposure = 0.25,
  [double]$FixedExposure = -6.0,
  [double]$WristExposure = -6.0,

  [Alias("InitConfigId")]
  [string]$BucketLabel = "bucket_001",
  # Max absolute randomization in degrees for a new bucket's initial arm pose.
  # 0 means exact HOME; 3 is a conservative first value.
  [double]$BucketRandomDeg = 3.0,
  [double]$BucketStartCountdownS = 2.0,
  [ValidateSet("autonomous", "intervention", "recovery", "demo", "eval")]
  [string]$Source = "autonomous",
  [ValidateSet("policy", "teleop")]
  [string]$StartControlMode = "policy",

  # Safer default: leader takeover is relative to the pose at switch time.
  # Use -AbsoluteTeleop only if the leader and follower are deliberately aligned.
  [switch]$AbsoluteTeleop,
  [switch]$NoLeader,
  # Optional: while human is controlling, periodically send observations to the
  # policy server for logging only; returned actions are ignored.
  [switch]$HumanSendPolicyObservations,

  [double[]]$JointOffsets = @(0, 0, 0, 0, 0, 0),
  [double[]]$JointScales = @(1, 1, 1, 1, 1, 1),
  [int]$DashboardFps = 15,
  [int]$DashboardCameraFps = 10,
  [int]$DashboardHistory = 0,
  [switch]$PrintServerResponses,
  [switch]$DryRun,
  [switch]$StreamingEncoding,
  [string]$VideoCodec = "libsvtav1",
  [int]$EncoderThreads = 0,
  [int]$EncoderQueueMaxsize = 30,

  [string]$Python = "C:\Users\19142\.conda\envs\g05-record-v3\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
  throw "G0.5 RL collection Python is missing: $Python"
}
if ($JointOffsets.Count -ne 6 -or $JointScales.Count -ne 6) {
  throw "JointOffsets and JointScales must each contain exactly six values."
}
if ($JointScales | Where-Object { $_ -le 0 }) {
  throw "Every JointScales entry must be positive."
}

$followerCalibrationFile = Join-Path $FollowerCalibrationDir "$FollowerId.json"
if (-not (Test-Path -LiteralPath $followerCalibrationFile)) {
  throw "Refusing to start automatic follower calibration. Missing: $followerCalibrationFile"
}

$leaderEnabled = (-not $NoLeader) -and ($LeaderPort.Trim().Length -gt 0)
if ($leaderEnabled) {
  $leaderCalibrationFile = Join-Path $LeaderCalibrationDir "$LeaderId.json"
  if (-not (Test-Path -LiteralPath $leaderCalibrationFile)) {
    throw "Refusing to start automatic leader calibration. Missing: $leaderCalibrationFile"
  }
} else {
  $leaderCalibrationFile = ""
  if ($StartControlMode -eq "teleop" -or $Source -in @("demo", "recovery")) {
    throw "Leader is disabled because -LeaderPort was not provided. Use -LeaderPort COMxx for teleop/demo/recovery, or start with -StartControlMode policy -Source autonomous."
  }
  if ($Source -eq "intervention") {
    Write-Warning "Source is intervention but no leader is enabled. You can still record policy data, but Teleop mode will be blocked."
  }
}

if ($RunName.Length -eq 0) {
  $RunName = Get-Date -Format "yyyyMMdd_HHmmss"
}
if ($BucketRoot.Length -eq 0) {
  $dataHome = Split-Path -Parent $DatasetBaseDir
  $BucketRoot = Join-Path (Join-Path $dataHome "g05_rl_buckets") $DatasetGroup
}
$datasetRoot = Join-Path (Join-Path $DatasetBaseDir $DatasetGroup) $RunName
$datasetRoot = [IO.Path]::GetFullPath($datasetRoot)
$BucketRoot = [IO.Path]::GetFullPath($BucketRoot)
if (Test-Path -LiteralPath $datasetRoot) {
  throw "Refusing to overwrite existing dataset directory: $datasetRoot"
}
$datasetRepo = "$DatasetNamespace/${DatasetGroup}_${RunName}" -replace "[^A-Za-z0-9_./-]", "_"

$collector = Join-Path $PSScriptRoot "g05_so101_rl_collector.py"
if (-not (Test-Path -LiteralPath $collector)) {
  throw "Collector script is missing: $collector"
}

if ($leaderEnabled) {
  Write-Warning "RL DATA COLLECTION TOOL WILL CONNECT TO FOLLOWER=$FollowerPort, LEADER=$LeaderPort, and cameras $FixedCameraIndex/$WristCameraIndex."
} else {
  Write-Warning "RL DATA COLLECTION TOOL WILL CONNECT TO FOLLOWER=$FollowerPort and cameras $FixedCameraIndex/$WristCameraIndex. Leader is disabled."
}
if ($DryRun) {
  Write-Warning "DRY RUN: dataset may be created, but follower actions are not sent."
} else {
  $null = Read-Host "Clear the workspace and keep power/torque stop within reach. Press Enter to connect"
}

$argsList = @(
  $collector,
  "--host", "127.0.0.1",
  "--port", "$PolicyPort",
  "--task", $Task,
  "--policy-ckpt-label", $PolicyCkptLabel,
  "--dataset-root", $datasetRoot,
  "--dataset-repo-id", $datasetRepo,
  "--bucket-root", $BucketRoot,
  "--dataset-fps", "$DatasetFps",
  "--action-fps", "$ActionFps",
  "--expected-action-steps", "$ExpectedActionSteps",
  "--timeout-s", "$TimeoutS",
  "--max-step-deg", "$MaxStepDeg",
  "--follower-port", $FollowerPort,
  "--follower-id", $FollowerId,
  "--leader-id", $LeaderId,
  "--follower-calibration-dir", $FollowerCalibrationDir,
  "--fixed-camera", "$FixedCameraIndex",
  "--wrist-camera", "$WristCameraIndex",
  "--fixed-crop-right-px", "$FixedCropRightPx",
  "--wrist-crop-right-px", "$WristCropRightPx",
  "--camera-fps", "$CameraFps",
  "--fixed-auto-exposure", "$FixedAutoExposure",
  "--wrist-auto-exposure", "$WristAutoExposure",
  "--fixed-exposure", "$FixedExposure",
  "--wrist-exposure", "$WristExposure",
  "--init-config-id", $BucketLabel,
  "--bucket-random-deg", "$BucketRandomDeg",
  "--bucket-start-countdown-s", "$BucketStartCountdownS",
  "--source", $Source,
  "--start-control-mode", $StartControlMode,
  "--dashboard-fps", "$DashboardFps",
  "--dashboard-camera-fps", "$DashboardCameraFps",
  "--dashboard-history", "$DashboardHistory",
  "--video-codec", $VideoCodec,
  "--encoder-queue-maxsize", "$EncoderQueueMaxsize"
)
if ($leaderEnabled) {
  $argsList += @(
    "--leader-port", $LeaderPort,
    "--leader-calibration-dir", $LeaderCalibrationDir
  )
} else {
  $argsList += "--no-leader"
}
$argsList += "--joint-offsets"
foreach ($value in $JointOffsets) { $argsList += "$value" }
$argsList += "--joint-scales"
foreach ($value in $JointScales) { $argsList += "$value" }

if ($AbsoluteTeleop) { $argsList += "--absolute-teleop" }
if ($HumanSendPolicyObservations) { $argsList += "--human-send-policy-observations" }
if ($PrintServerResponses) { $argsList += "--print-server-responses" }
if ($DryRun) { $argsList += "--dry-run" }
if ($StreamingEncoding) { $argsList += "--streaming-encoding" }
if ($EncoderThreads -gt 0) { $argsList += @("--encoder-threads", "$EncoderThreads") }

Write-Host "G0.5 SO101 RL collector"
Write-Host "  dataset:    $datasetRoot"
Write-Host "  buckets:    $BucketRoot"
Write-Host "  task:       $Task"
Write-Host "  source:     $Source; bucket label: $BucketLabel; new-bucket random +/- $BucketRandomDeg deg; start mode: $StartControlMode"
Write-Host "  policy:     ws://127.0.0.1:$PolicyPort; action=$ActionFps Hz; dataset=$DatasetFps Hz; chunk=$ExpectedActionSteps; max step=$MaxStepDeg deg"
Write-Host "  cameras:    fixed=$FixedCameraIndex crop-right=$FixedCropRightPx; wrist=$WristCameraIndex crop-right=$WristCropRightPx"
Write-Host "  video:      codec=$VideoCodec; streaming=$StreamingEncoding; encoder_threads=$EncoderThreads"
if ($leaderEnabled) {
  Write-Host "  leader:     $LeaderPort; relative takeover=$(-not $AbsoluteTeleop); background policy obs during human=$HumanSendPolicyObservations"
} else {
  Write-Host "  leader:     disabled; autonomous/policy-only collection"
}
Write-Host "  labels:     $datasetRoot\rl_rollout_labels.jsonl"
Write-Host "  events:     $datasetRoot\rl_events.jsonl"

& $Python @argsList
exit $LASTEXITCODE


# .\scripts\g0.5\rl\run_g05_rl_collector.ps1 `
#   -PolicyCkptLabel "g05_ar_sft_pick_white_20260701" `
#   -LeaderPort COM22 `
#   -StreamingEncoding `
#   -EncoderThreads 2
