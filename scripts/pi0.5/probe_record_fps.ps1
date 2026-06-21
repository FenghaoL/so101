# Probe the effective recording FPS for the SO101 setup.
#
# Run from an Anaconda PowerShell Prompt after:
#   conda activate lerobot
#
# Usage:
#   .\scripts\probe_record_fps.ps1
#   .\scripts\probe_record_fps.ps1 -RequestedFps 30 -ApplyRecommended
#
# During the probe:
#   1. Wait for "Recording episode 0".
#   2. Do one short representative task.
#   3. Press Right Arrow when the task is done.
#
# The script compares:
#   - video time: frames / dataset fps
#   - real time: wall-clock time from "Recording episode" to Right Arrow

param(
  [int]$RequestedFps = 30,

  [string]$DatasetBaseDir = "D:\workspace\Manipulation\so101\so101_data",

  [string]$DatasetNamespace = "fenghao",

  [switch]$ApplyRecommended
)

$ErrorActionPreference = "Stop"

function Get-FirstJsonLine($Path) {
  if (-not (Test-Path $Path)) {
    throw "Missing file: $Path"
  }
  $line = Get-Content -Path $Path | Select-Object -First 1
  if (-not $line) {
    throw "Empty file: $Path"
  }
  return ($line | ConvertFrom-Json)
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$datasetRoot = Join-Path $DatasetBaseDir "fps_probe"
$datasetRoot = Join-Path $datasetRoot $timestamp
$datasetRoot = [System.IO.Path]::GetFullPath($datasetRoot)
$datasetRootArg = $datasetRoot -replace "\\", "/"
$datasetRepo = "$DatasetNamespace/so101_fps_probe_$timestamp"

$cameraConfig = "{ fixed: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: $RequestedFps}, wrist: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: $RequestedFps}}"
$task = "fps probe"

New-Item -ItemType Directory -Force -Path (Split-Path $datasetRoot -Parent) | Out-Null

Write-Host "FPS probe dataset root: $datasetRoot"
Write-Host "Requested FPS: $RequestedFps"
Write-Host ""
Write-Host "Instructions:"
Write-Host "  1. Wait until you see: Recording episode 0"
Write-Host "  2. Do one normal short task."
Write-Host "  3. Press Right Arrow when the task is done."
Write-Host ""
Write-Host "The probe starts now."
Write-Host ""

$previousPythonUnbuffered = $env:PYTHONUNBUFFERED
$env:PYTHONUNBUFFERED = "1"

$recordStart = $null
$recordEnd = $null

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
    "--dataset.single_task=$task",
    "--dataset.fps=$RequestedFps",
    "--dataset.episode_time_s=60",
    "--dataset.reset_time_s=3600",
    "--dataset.push_to_hub=False",
    "--resume=False",
    "--display_data=False"
  )

  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & lerobot-record @recordArgs 2>&1 | ForEach-Object {
      $line = $_.ToString()
      if ($null -eq $recordStart -and $line -match "Recording episode") {
        $recordStart = Get-Date
      }
      if ($null -eq $recordEnd -and $line -match "Right arrow key pressed") {
        $recordEnd = Get-Date
      }
      Write-Host $line
    }
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
$episode = Get-FirstJsonLine $episodesPath

$frames = [int]$episode.length
$datasetFps = [double]$info.fps
$videoSeconds = $frames / $datasetFps

if ($null -ne $recordStart -and $null -ne $recordEnd) {
  $realSeconds = ($recordEnd - $recordStart).TotalSeconds
} else {
  Write-Host ""
  Write-Host "Could not detect the real-time boundary from logs."
  $manual = Read-Host "Enter the real task duration in seconds"
  $realSeconds = [double]$manual
}

$effectiveFps = $frames / $realSeconds
$recommendedFps = [Math]::Max(5, [Math]::Min(30, [int][Math]::Round($effectiveFps)))
$speedRatio = $videoSeconds / $realSeconds

Write-Host ""
Write-Host "Probe result"
Write-Host "------------"
Write-Host ("Saved frames:      {0}" -f $frames)
Write-Host ("Dataset FPS:       {0:N2}" -f $datasetFps)
Write-Host ("Video time:        {0:N2} s" -f $videoSeconds)
Write-Host ("Real time:         {0:N2} s" -f $realSeconds)
Write-Host ("Effective FPS:     {0:N2}" -f $effectiveFps)
Write-Host ("Video/real ratio:  {0:P1}" -f $speedRatio)
Write-Host ("Recommended FPS:   {0}" -f $recommendedFps)

if ($ApplyRecommended) {
  $recordTaskPath = Join-Path $PSScriptRoot "record_task.ps1"
  $text = Get-Content -Path $recordTaskPath -Raw
  $text = $text -replace "\[int\]\`$DatasetFps = \d+", "[int]`$DatasetFps = $recommendedFps"
  $text = $text -replace "\[int\]\`$CameraFps = \d+", "[int]`$CameraFps = $recommendedFps"
  Set-Content -Path $recordTaskPath -Value $text -Encoding UTF8
  Write-Host ""
  Write-Host "Applied recommended FPS to scripts\record_task.ps1"
}
