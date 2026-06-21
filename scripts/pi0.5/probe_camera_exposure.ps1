# Probe OpenCV/DirectShow auto-exposure settings for one camera.
#
# Run from an Anaconda PowerShell Prompt after:
#   conda activate lerobot
#
# Example:
#   .\scripts\probe_camera_exposure.ps1 -CameraIndex 0

param(
  [int]$CameraIndex = 0,

  [int]$MeasureSeconds = 4
)

$ErrorActionPreference = "Stop"

$pythonScript = Join-Path $PSScriptRoot "probe_camera_exposure.py"

Write-Host "OpenCV camera exposure probe"
Write-Host "----------------------------"
Write-Host "Camera index:    $CameraIndex"
Write-Host "Measure seconds: $MeasureSeconds"
Write-Host ""

& python $pythonScript `
  --camera-index $CameraIndex `
  --measure-seconds $MeasureSeconds

