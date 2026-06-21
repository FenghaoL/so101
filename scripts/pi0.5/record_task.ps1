# Record one SO101 task into a fresh timestamped LeRobot dataset.
#
# Run from an Anaconda PowerShell Prompt after:
#   conda activate lerobot
#
# Keyboard controls during lerobot-record:
#   Right Arrow: finish the current recording/reset phase early.
#   Left Arrow: discard and re-record the current episode.
#   Esc: stop the whole recording run.
#   Ctrl+C: emergency stop only; avoid it for normal episode boundaries.

param(
  [Parameter(Mandatory = $true)]
  [string]$Task,

  [int]$Episodes = 30,

  [string]$DatasetBaseDir = "D:\workspace\Manipulation\so101\so101_data",

  [string]$DatasetGroup = "so101_objects_v1",

  [string]$TaskFolder = "",

  [string]$DatasetNamespace = "fenghao",

  [string]$RunName = "",

  [switch]$Resume,

  [int]$DatasetFps = 18,

  [int]$CameraFps = 20,

  [double]$WristExposure = -5.0,

  [double]$FixedExposure = -5.0,

  [int]$EpisodeTimeS = 60,

  [int]$ResetTimeS = 3600,

  [switch]$DisplayData
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location (Join-Path $repoRoot "lerobot")

try {
  $displayValue = $DisplayData.IsPresent.ToString().ToLowerInvariant()
  $resumeValue = $Resume.IsPresent.ToString().ToLowerInvariant()
  $fixedExposureConfig = if ([double]::IsNaN($FixedExposure)) { "" } else { ", exposure: $FixedExposure" }
  $wristExposureConfig = if ([double]::IsNaN($WristExposure)) { "" } else { ", exposure: $WristExposure" }
  $cameraConfig = "{ fixed: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: $CameraFps$fixedExposureConfig}, wrist: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: $CameraFps$wristExposureConfig}}"
  $timestamp = if ($RunName.Length -gt 0) { $RunName } else { Get-Date -Format "yyyyMMdd_HHmmss" }

  if ($TaskFolder.Length -eq 0) {
    $TaskFolder = $Task.ToLowerInvariant() -replace "[^a-z0-9]+", "_"
    $TaskFolder = $TaskFolder.Trim("_")
  }

  $datasetRoot = Join-Path $DatasetBaseDir $DatasetGroup
  $datasetRoot = Join-Path $datasetRoot $TaskFolder
  $datasetRoot = Join-Path $datasetRoot $timestamp
  $datasetRoot = [System.IO.Path]::GetFullPath($datasetRoot)
  $datasetRootArg = $datasetRoot -replace "\\", "/"

  $datasetRepo = "$DatasetNamespace/${DatasetGroup}_${TaskFolder}_${timestamp}"
  $datasetRepo = $datasetRepo -replace "[^A-Za-z0-9_./-]", "_"

  New-Item -ItemType Directory -Force -Path (Split-Path $datasetRoot -Parent) | Out-Null

  Write-Host "Dataset repo id: $datasetRepo"
  Write-Host "Dataset root: $datasetRoot"
  Write-Host "Dataset group: $DatasetGroup"
  Write-Host "Task folder: $TaskFolder"
  Write-Host "Run folder: $timestamp"
  Write-Host "Task: $Task"
  Write-Host "Episodes in this run: $Episodes"
  Write-Host "Resume existing dataset: $resumeValue"
  Write-Host "Dataset FPS: $DatasetFps"
  Write-Host "Camera FPS: $CameraFps"
  Write-Host "Fixed exposure: $FixedExposure"
  Write-Host "Wrist exposure: $WristExposure"
  Write-Host "Display/Rerun: $displayValue"
  Write-Host ""
  Write-Host "Make sure the scene is ready BEFORE pressing Enter in lerobot-record prompts."
  Write-Host ""

  lerobot-record `
    --robot.type=so101_follower --robot.port=COM24 --robot.id=fenghao_so101_follower `
    --robot.cameras="$cameraConfig" `
    --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=fenghao_so101_leader `
    --dataset.repo_id="$datasetRepo" `
    --dataset.root="$datasetRootArg" `
    --dataset.num_episodes=$Episodes `
    --dataset.single_task="$Task" `
    --dataset.fps=$DatasetFps `
    --dataset.episode_time_s=$EpisodeTimeS `
    --dataset.reset_time_s=$ResetTimeS `
    --dataset.push_to_hub=False `
    --resume=$resumeValue `
    --display_data=$displayValue
}
finally {
  Pop-Location
}
