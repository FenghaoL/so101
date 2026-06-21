# Probe the effective SO101 recording throughput with a fixed-duration episode.
#
# Run from an Anaconda PowerShell Prompt after:
#   conda activate lerobot
#
# Usage:
#   .\scripts\probe_record_timed_fps.ps1
#   .\scripts\probe_record_timed_fps.ps1 -RequestedFps 30 -DurationS 10
#
# This records exactly one episode and lets lerobot-record stop it by time.
# Do not press arrow keys during the probe.

param(
  [int]$RequestedFps = 30,

  [int]$DurationS = 10,

  [int]$Width = 640,

  [int]$Height = 480,

  [double]$WristExposure = [double]::NaN,

  [double]$FixedExposure = [double]::NaN,

  [ValidateSet("both", "fixed", "wrist", "none")]
  [string]$CameraMode = "both",

  [string]$DatasetBaseDir = "D:\workspace\Manipulation\so101\so101_data",

  [string]$DatasetNamespace = "fenghao"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$datasetRoot = Join-Path $DatasetBaseDir "fps_probe_timed"
$datasetRoot = Join-Path $datasetRoot ("{0}_{1}fps_{2}_{3}s" -f $timestamp, $RequestedFps, $CameraMode, $DurationS)
$datasetRoot = [System.IO.Path]::GetFullPath($datasetRoot)
$datasetRootArg = $datasetRoot -replace "\\", "/"
$datasetRepo = "$DatasetNamespace/so101_fps_probe_timed_${timestamp}_${CameraMode}"

switch ($CameraMode) {
  "both" {
    $fixedExposureConfig = if ([double]::IsNaN($FixedExposure)) { "" } else { ", exposure: $FixedExposure" }
    $wristExposureConfig = if ([double]::IsNaN($WristExposure)) { "" } else { ", exposure: $WristExposure" }
    $cameraConfig = "{ fixed: {type: opencv, index_or_path: 2, width: $Width, height: $Height, fps: $RequestedFps$fixedExposureConfig}, wrist: {type: opencv, index_or_path: 0, width: $Width, height: $Height, fps: $RequestedFps$wristExposureConfig}}"
  }
  "fixed" {
    $fixedExposureConfig = if ([double]::IsNaN($FixedExposure)) { "" } else { ", exposure: $FixedExposure" }
    $cameraConfig = "{ fixed: {type: opencv, index_or_path: 2, width: $Width, height: $Height, fps: $RequestedFps$fixedExposureConfig}}"
  }
  "wrist" {
    $wristExposureConfig = if ([double]::IsNaN($WristExposure)) { "" } else { ", exposure: $WristExposure" }
    $cameraConfig = "{ wrist: {type: opencv, index_or_path: 0, width: $Width, height: $Height, fps: $RequestedFps$wristExposureConfig}}"
  }
  "none" {
    $cameraConfig = "{}"
  }
}

New-Item -ItemType Directory -Force -Path (Split-Path $datasetRoot -Parent) | Out-Null

Write-Host "Timed FPS probe"
Write-Host "---------------"
Write-Host "Dataset root:  $datasetRoot"
Write-Host "Requested FPS: $RequestedFps"
Write-Host "Duration:      $DurationS s"
Write-Host "Camera mode:   $CameraMode"
Write-Host "Resolution:    ${Width}x${Height}"
Write-Host "Fixed exposure: $FixedExposure"
Write-Host "Wrist exposure: $WristExposure"
Write-Host ""
Write-Host "Do not press arrow keys. Move the leader normally during the probe if you want representative load."
Write-Host ""

$previousPythonUnbuffered = $env:PYTHONUNBUFFERED
$env:PYTHONUNBUFFERED = "1"
$exitCode = 0

Push-Location (Join-Path $repoRoot "lerobot")
try {
  $recordArgs = @(
    "--robot.type=so101_follower",
    "--robot.port=COM24",
    "--robot.id=fenghao_so101_follower",
    "--robot.cameras=$cameraConfig",
    "--teleop.type=so101_leader",
    "--teleop.port=COM22",
    "--teleop.id=fenghao_so101_leader",
    "--dataset.repo_id=$datasetRepo",
    "--dataset.root=$datasetRootArg",
    "--dataset.num_episodes=1",
    "--dataset.single_task=fps probe timed",
    "--dataset.fps=$RequestedFps",
    "--dataset.episode_time_s=$DurationS",
    "--dataset.reset_time_s=3600",
    "--dataset.push_to_hub=False",
    "--resume=False",
    "--display_data=False"
  )

  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & lerobot-record @recordArgs 2>&1 | ForEach-Object { Write-Host $_.ToString() }
    $exitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
}
finally {
  Pop-Location
  if ($null -eq $previousPythonUnbuffered) {
    Remove-Item Env:\PYTHONUNBUFFERED -ErrorAction SilentlyContinue
  } else {
    $env:PYTHONUNBUFFERED = $previousPythonUnbuffered
  }
}

if ($exitCode -ne 0) {
  throw "lerobot-record exited with code $exitCode"
}

$infoPath = Join-Path $datasetRoot "meta\info.json"
$episodesPath = Join-Path $datasetRoot "meta\episodes.jsonl"
$info = Get-Content -Path $infoPath -Raw | ConvertFrom-Json
$episode = (Get-Content -Path $episodesPath | Select-Object -First 1) | ConvertFrom-Json

$frames = [int]$episode.length
$datasetFps = [double]$info.fps
$videoSeconds = $frames / $datasetFps
$effectiveFps = $frames / $DurationS
$recommendedFps = [Math]::Max(5, [Math]::Min(30, [int][Math]::Round($effectiveFps)))
$speedRatio = $videoSeconds / $DurationS

Write-Host ""
Write-Host "Timed probe result"
Write-Host "------------------"
Write-Host ("Saved frames:      {0}" -f $frames)
Write-Host ("Dataset FPS:       {0:N2}" -f $datasetFps)
Write-Host ("Video time:        {0:N2} s" -f $videoSeconds)
Write-Host ("Real time:         {0:N2} s" -f $DurationS)
Write-Host ("Effective FPS:     {0:N2}" -f $effectiveFps)
Write-Host ("Video/real ratio:  {0:P1}" -f $speedRatio)
Write-Host ("Recommended FPS:   {0}" -f $recommendedFps)
