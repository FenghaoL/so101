[CmdletBinding()]
param(
  [string]$Task = "Pick up the white block.",
  [string]$DatasetBaseDir = "D:\workspace\Manipulation\so101\so101_data\g05_rl_raw",
  [string]$DatasetGroup = "so101_g05_rl_pick_white_v1",
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
  [string]$LeaderPort = "COM22",
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

  [string]$InitConfigId = "A_mean_home",
  [ValidateSet("autonomous", "intervention", "recovery", "demo", "eval")]
  [string]$Source = "autonomous",
  [ValidateSet("policy", "teleop")]
  [string]$StartControlMode = "policy",

  # Safer default: leader takeover is relative to the pose at switch time.
  # Use -AbsoluteTeleop only if the leader and follower are deliberately aligned.
  [switch]$AbsoluteTeleop,
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
$leaderCalibrationFile = Join-Path $LeaderCalibrationDir "$LeaderId.json"
if (-not (Test-Path -LiteralPath $followerCalibrationFile)) {
  throw "Refusing to start automatic follower calibration. Missing: $followerCalibrationFile"
}
if (-not (Test-Path -LiteralPath $leaderCalibrationFile)) {
  throw "Refusing to start automatic leader calibration. Missing: $leaderCalibrationFile"
}

if ($RunName.Length -eq 0) {
  $RunName = Get-Date -Format "yyyyMMdd_HHmmss"
}
$datasetRoot = Join-Path (Join-Path $DatasetBaseDir $DatasetGroup) $RunName
$datasetRoot = [IO.Path]::GetFullPath($datasetRoot)
if (Test-Path -LiteralPath $datasetRoot) {
  throw "Refusing to overwrite existing dataset directory: $datasetRoot"
}
$datasetRepo = "$DatasetNamespace/${DatasetGroup}_${RunName}" -replace "[^A-Za-z0-9_./-]", "_"

$collector = Join-Path $PSScriptRoot "g05_so101_rl_collector.py"
if (-not (Test-Path -LiteralPath $collector)) {
  throw "Collector script is missing: $collector"
}

Write-Warning "RL DATA COLLECTION TOOL WILL CONNECT TO FOLLOWER=$FollowerPort, LEADER=$LeaderPort, and cameras $FixedCameraIndex/$WristCameraIndex."
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
  "--dataset-fps", "$DatasetFps",
  "--action-fps", "$ActionFps",
  "--expected-action-steps", "$ExpectedActionSteps",
  "--timeout-s", "$TimeoutS",
  "--max-step-deg", "$MaxStepDeg",
  "--follower-port", $FollowerPort,
  "--leader-port", $LeaderPort,
  "--follower-id", $FollowerId,
  "--leader-id", $LeaderId,
  "--follower-calibration-dir", $FollowerCalibrationDir,
  "--leader-calibration-dir", $LeaderCalibrationDir,
  "--fixed-camera", "$FixedCameraIndex",
  "--wrist-camera", "$WristCameraIndex",
  "--fixed-crop-right-px", "$FixedCropRightPx",
  "--wrist-crop-right-px", "$WristCropRightPx",
  "--camera-fps", "$CameraFps",
  "--fixed-auto-exposure", "$FixedAutoExposure",
  "--wrist-auto-exposure", "$WristAutoExposure",
  "--fixed-exposure", "$FixedExposure",
  "--wrist-exposure", "$WristExposure",
  "--init-config-id", $InitConfigId,
  "--source", $Source,
  "--start-control-mode", $StartControlMode,
  "--dashboard-fps", "$DashboardFps",
  "--dashboard-camera-fps", "$DashboardCameraFps",
  "--dashboard-history", "$DashboardHistory",
  "--joint-offsets"
)
foreach ($value in $JointOffsets) { $argsList += "$value" }
$argsList += "--joint-scales"
foreach ($value in $JointScales) { $argsList += "$value" }

if ($AbsoluteTeleop) { $argsList += "--absolute-teleop" }
if ($HumanSendPolicyObservations) { $argsList += "--human-send-policy-observations" }
if ($PrintServerResponses) { $argsList += "--print-server-responses" }
if ($DryRun) { $argsList += "--dry-run" }

Write-Host "G0.5 SO101 RL collector"
Write-Host "  dataset:    $datasetRoot"
Write-Host "  task:       $Task"
Write-Host "  source:     $Source; init bucket: $InitConfigId; start mode: $StartControlMode"
Write-Host "  policy:     ws://127.0.0.1:$PolicyPort; action=$ActionFps Hz; dataset=$DatasetFps Hz; chunk=$ExpectedActionSteps; max step=$MaxStepDeg deg"
Write-Host "  cameras:    fixed=$FixedCameraIndex crop-right=$FixedCropRightPx; wrist=$WristCameraIndex crop-right=$WristCropRightPx"
Write-Host "  teleop:     relative takeover=$(-not $AbsoluteTeleop); background policy obs during human=$HumanSendPolicyObservations"
Write-Host "  labels:     $datasetRoot\rl_rollout_labels.jsonl"
Write-Host "  events:     $datasetRoot\rl_events.jsonl"

& $Python @argsList
exit $LASTEXITCODE
