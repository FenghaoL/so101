# Probe raw OpenCV camera modes without going through LeRobot's strict validation.
#
# Run from an Anaconda PowerShell Prompt after:
#   conda activate lerobot
#
# Examples:
#   .\scripts\probe_camera_modes.ps1 -CameraIndex 0
#   .\scripts\probe_camera_modes.ps1 -CameraIndex 2 -MeasureSeconds 5

param(
  [int]$CameraIndex = 0,

  [string[]]$Modes = @("640x480", "320x240"),

  [int[]]$RequestedFps = @(30, 15, 10, 6),

  [string[]]$Fourcc = @("DEFAULT", "MJPG", "YUY2"),

  [int]$MeasureSeconds = 4
)

$ErrorActionPreference = "Stop"

Write-Host "Raw OpenCV camera mode probe"
Write-Host "----------------------------"
Write-Host "Camera index:    $CameraIndex"
Write-Host "Modes:           $($Modes -join ', ')"
Write-Host "Requested FPS:   $($RequestedFps -join ', ')"
Write-Host "FOURCC:          $($Fourcc -join ', ')"
Write-Host "Measure seconds: $MeasureSeconds"
Write-Host ""

$pythonScript = Join-Path $PSScriptRoot "probe_camera_modes.py"

& python $pythonScript `
  --camera-index $CameraIndex `
  --modes $Modes `
  --requested-fps $RequestedFps `
  --fourcc $Fourcc `
  --measure-seconds $MeasureSeconds
