[CmdletBinding()]
param(
  # Keep the language instruction identical between demonstrations and deployment.
  [Parameter(Mandatory = $true)]
  [string]$Task,

  [int]$Episodes = 1,
  [string]$DatasetBaseDir = "D:\workspace\Manipulation\so101\so101_data\g05_raw",
  [string]$DatasetGroup = "so101_g05_v3",
  [string]$TaskFolder = "",
  [string]$RunName = "",
  [string]$DatasetNamespace = "fenghao",
  [int]$DatasetFps = 15,
  [int]$CameraFps = 30,
  [int]$EpisodeTimeS = 60,
  [int]$ResetTimeS = 600,

  [int]$FixedCameraIndex = 2,
  [int]$WristCameraIndex = 0,
  [double]$FixedAutoExposure = 0.25,
  [double]$WristAutoExposure = 0.25,
  [double]$FixedExposure = -6.0,
  [double]$WristExposure = -6.0,

  [string]$FollowerPort = "COM24",
  [string]$LeaderPort = "COM22",
  [string]$FollowerId = "fenghao_so101_follower",
  [string]$LeaderId = "fenghao_so101_leader",

  # LeRobot 0.5.1's generic SO classes otherwise look under so_follower /
  # so_leader.  These point to the existing, known SO101 calibration files
  # used by the hardware-tested local environment.
  [string]$FollowerCalibrationDir = "$env:USERPROFILE\.cache\huggingface\lerobot\calibration\robots\so101_follower",
  [string]$LeaderCalibrationDir = "$env:USERPROFILE\.cache\huggingface\lerobot\calibration\teleoperators\so101_leader",

  # This is deliberately the exact live-client image contract: remove the
  # rightmost round(640 / 7) = 91 pixels, retaining a 549x480 exterior frame.
  # The raw dataset stays 640x480; the manifest records this contract and the
  # G0.5 training adapter applies the same crop while loading it.
  [int]$FixedCropRightPx = 91,
  [int]$WristCropRightPx = 0,

  [switch]$DisplayData,
  [switch]$Resume,

  [string]$Python = "C:\Users\19142\.conda\envs\g05-record-v3\python.exe"
)

$ErrorActionPreference = "Stop"

if ($Episodes -le 0) { throw "Episodes must be positive." }
if ($DatasetFps -ne 15) {
  Write-Warning "DatasetFps=$DatasetFps. The deployed G0.5 client is 15 Hz, so a 32-step target covers $(32.0 / $DatasetFps) seconds rather than the live 2.13 seconds."
}
if ($CameraFps -lt $DatasetFps) { throw "CameraFps must be at least DatasetFps." }
if ($FixedCropRightPx -lt 0 -or $FixedCropRightPx -ge 640) { throw "FixedCropRightPx must be in [0, 639]." }
if ($WristCropRightPx -lt 0 -or $WristCropRightPx -ge 640) { throw "WristCropRightPx must be in [0, 639]." }
if (-not (Test-Path -LiteralPath $Python)) {
  throw "G0.5 recording Python is missing: $Python. Create/repair the g05-record-v3 environment first."
}

$recordWrapper = Join-Path $PSScriptRoot "record_g05_with_camera_controls.py"
if (-not (Test-Path -LiteralPath $recordWrapper)) {
  throw "Recording camera-control wrapper is missing: $recordWrapper"
}

$followerCalibrationFile = Join-Path $FollowerCalibrationDir "$FollowerId.json"
$leaderCalibrationFile = Join-Path $LeaderCalibrationDir "$LeaderId.json"
if (-not (Test-Path -LiteralPath $followerCalibrationFile)) {
  throw "Refusing to start an automatic calibration. Expected follower calibration: $followerCalibrationFile"
}
if (-not (Test-Path -LiteralPath $leaderCalibrationFile)) {
  throw "Refusing to start an automatic calibration. Expected leader calibration: $leaderCalibrationFile"
}

if ($TaskFolder.Length -eq 0) {
  $TaskFolder = ($Task.ToLowerInvariant() -replace "[^a-z0-9]+", "_").Trim("_")
}
if ($RunName.Length -eq 0) {
  $RunName = Get-Date -Format "yyyyMMdd_HHmmss"
}

$datasetRoot = Join-Path (Join-Path (Join-Path $DatasetBaseDir $DatasetGroup) $TaskFolder) $RunName
$datasetRoot = [IO.Path]::GetFullPath($datasetRoot)
if (Test-Path -LiteralPath $datasetRoot) {
  throw "Refusing to overwrite an existing dataset directory: $datasetRoot`nUse -RunName to choose a new run."
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $datasetRoot) | Out-Null

$datasetRepo = "$DatasetNamespace/${DatasetGroup}_${TaskFolder}_${RunName}" -replace "[^A-Za-z0-9_./-]", "_"
# LeRobot 0.5.1 accepts these standard camera fields.  The camera-control
# wrapper applies auto_exposure/exposure directly to these same handles before
# their frame threads start, because current LeRobot no longer has those two
# configuration fields.
$cameraConfig = "{ fixed: {type: opencv, index_or_path: $FixedCameraIndex, width: 640, height: 480, fps: $CameraFps}, wrist: {type: opencv, index_or_path: $WristCameraIndex, width: 640, height: 480, fps: $CameraFps}}"
$cameraControls = [ordered]@{
  "$FixedCameraIndex" = [ordered]@{ auto_exposure = $FixedAutoExposure; exposure = $FixedExposure }
  "$WristCameraIndex" = [ordered]@{ auto_exposure = $WristAutoExposure; exposure = $WristExposure }
}

# Both arms must use degrees. Setting it on only the follower would make the
# leader's normalized [-100, 100] command values unsafe and inconsistent.
$recordArgs = @(
  "--robot.type=so101_follower",
  "--robot.port=$FollowerPort",
  "--robot.id=$FollowerId",
  "--robot.calibration_dir=$($FollowerCalibrationDir -replace '\\', '/')",
  "--robot.use_degrees=true",
  "--robot.cameras=$cameraConfig",
  "--teleop.type=so101_leader",
  "--teleop.port=$LeaderPort",
  "--teleop.id=$LeaderId",
  "--teleop.calibration_dir=$($LeaderCalibrationDir -replace '\\', '/')",
  "--teleop.use_degrees=true",
  "--dataset.repo_id=$datasetRepo",
  "--dataset.root=$($datasetRoot -replace '\\', '/')",
  "--dataset.num_episodes=$Episodes",
  "--dataset.single_task=$Task",
  "--dataset.fps=$DatasetFps",
  "--dataset.episode_time_s=$EpisodeTimeS",
  "--dataset.reset_time_s=$ResetTimeS",
  "--dataset.push_to_hub=false",
  "--display_data=$($DisplayData.IsPresent.ToString().ToLowerInvariant())",
  "--resume=$($Resume.IsPresent.ToString().ToLowerInvariant())"
)

Write-Host "G0.5 SO101 raw-data recorder"
Write-Host "  environment:  $Python"
Write-Host "  dataset:      $datasetRoot"
Write-Host "  task:         $Task"
Write-Host "  frequency:    $DatasetFps Hz data, $CameraFps Hz camera capture"
Write-Host "  cameras:      fixed=$FixedCameraIndex, wrist=$WristCameraIndex"
Write-Host "  exposure:     fixed auto=$FixedAutoExposure value=$FixedExposure; wrist auto=$WristAutoExposure value=$WristExposure"
Write-Host "  G0.5 images:  fixed $(640 - $FixedCropRightPx)x480 after right crop=$FixedCropRightPx px; wrist $(640 - $WristCropRightPx)x480 after right crop=$WristCropRightPx px"
Write-Host "  joint units:  degrees on both follower and leader"
Write-Host "  calibration:  follower=$followerCalibrationFile"
Write-Host "                leader=$leaderCalibrationFile"
Write-Host ""
Write-Host "During recording: Right Arrow ends an episode early; Left Arrow discards it; Escape stops the run."
Write-Host "Keep only successful, complete demonstrations."
Write-Host "If LeRobot reports a calibration mismatch, press ENTER only to write the listed existing SO101 calibration back to the motors. Do NOT type 'c' to create a new calibration."

$oldControlValue = $env:G05_RECORD_CAMERA_CONTROLS
$hadOldControlValue = Test-Path Env:G05_RECORD_CAMERA_CONTROLS
$env:G05_RECORD_CAMERA_CONTROLS = $cameraControls | ConvertTo-Json -Compress -Depth 4
$recordExit = $null
try {
  & $Python $recordWrapper @recordArgs
  $recordExit = $LASTEXITCODE
} finally {
  if ($hadOldControlValue) {
    $env:G05_RECORD_CAMERA_CONTROLS = $oldControlValue
  } else {
    Remove-Item Env:G05_RECORD_CAMERA_CONTROLS -ErrorAction SilentlyContinue
  }
}
if ($recordExit -ne 0) {
  throw "lerobot-record failed with exit code $recordExit. The dataset, if partially written, is intentionally left untouched for inspection."
}

# Preserve the exact calibration references used to interpret degree values.
$contextDir = Join-Path $datasetRoot "recording_context"
New-Item -ItemType Directory -Force -Path $contextDir | Out-Null
$cacheRoot = Join-Path $env:USERPROFILE ".cache\huggingface\lerobot\calibration"
$calibrationSources = @(
  (Join-Path $cacheRoot "robots\so101_follower\$FollowerId.json"),
  (Join-Path $cacheRoot "teleoperators\so101_leader\$LeaderId.json")
)
foreach ($source in $calibrationSources) {
  if (Test-Path -LiteralPath $source) {
    Copy-Item -LiteralPath $source -Destination $contextDir -Force
  } else {
    Write-Warning "Calibration file was not found for snapshotting: $source"
  }
}

$contract = [ordered]@{
  created_at = (Get-Date).ToString("o")
  task = $Task
  dataset_fps = $DatasetFps
  camera_capture_fps = $CameraFps
  raw_camera_fields = [ordered]@{ fixed = "observation.images.fixed"; wrist = "observation.images.wrist" }
  live_model_slots = [ordered]@{ fixed = "exterior"; wrist = "wrist_right"; wrist_left = "zero_padded" }
  live_image_contract = [ordered]@{ fixed_crop_right_px = $FixedCropRightPx; wrist_crop_right_px = $WristCropRightPx }
  requested_camera_controls = $cameraControls
  joint_recording_frame = "LeRobot calibrated degrees"
  required_model_frame = "signs*[pan,lift,elbow,wrist_flex,wrist_roll,gripper]+[0,90,90,0,0,0], signs=[1,-1,1,1,1,1]"
  follower = [ordered]@{ id = $FollowerId; port = $FollowerPort }
  leader = [ordered]@{ id = $LeaderId; port = $LeaderPort }
}
$contract | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $contextDir "g05_recording_contract.json") -Encoding utf8

$prepareScript = Join-Path $PSScriptRoot "prepare_g05_so101_dataset.py"
& $Python $prepareScript --source $datasetRoot --verify-only --expect-fps $DatasetFps --fixed-crop-right-px $FixedCropRightPx --wrist-crop-right-px $WristCropRightPx
if ($LASTEXITCODE -ne 0) {
  throw "Recording completed, but the G0.5 schema check failed. Do not begin full recording until this is resolved."
}

Write-Host ""
Write-Host "Schema check passed. To create the non-destructive G0.5 model-frame dataset, run:"
Write-Host "  & `"$Python`" `"$prepareScript`" --source `"$datasetRoot`" --destination `"$($datasetRoot)_g05_model_frame`""
