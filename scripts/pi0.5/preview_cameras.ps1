# Preview SO101 teleoperation with both cameras.
# Run from an Anaconda PowerShell Prompt after:
#   conda activate lerobot

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location (Join-Path $repoRoot "lerobot")

try {
  Write-Host "Camera discovery:"
  lerobot-find-cameras opencv

  Write-Host ""
  Write-Host "Starting camera preview teleoperation. This does not record a dataset."
  Write-Host "Press Ctrl+C to stop preview."

  lerobot-teleoperate `
    --fps 30 `
    --robot.type=so101_follower --robot.port=COM24 --robot.id=fenghao_so101_follower `
    --robot.cameras="{ fixed: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 15}, wrist: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 15}}" `
    --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=fenghao_so101_leader `
    --display_data=true
}
finally {
  Pop-Location
}
