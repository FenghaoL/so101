[CmdletBinding()]
param(
  # G0.5 SO-101 expects English instructions. Keep this short and make sure
  # the named object and destination are visible in the two camera views.
  [string]$Task = "pick up the white block",
  # Other zero-shot prompts, one at a time:
  # [string]$Task = "put the red block into the blue bowl"
  # [string]$Task = "move the wooden cube to the right"
  # [string]$Task = "pick up the yellow screwdriver"

  # Re-check these after USB replugging with: lerobot-find-cameras opencv
  # The existing pi0.5 setup used fixed=2 and wrist=0.
  [int]$FixedCameraIndex = 2,
  [int]$WristCameraIndex = 0,

  # The fixed camera is cropped to a square before server resize. The wrist
  # camera keeps its complete 640x480 frame and is stretched by the server.
  [int]$FixedCropRightPx = 160,
  [int]$WristCropRightPx = 0,

  # DirectShow/UVC exposure values. They are applied when each camera opens.
  # -5 was the previous pi0.5 setting; reduce further (-6, -7...) if needed.
  [double]$FixedExposure = -5.0,
  [double]$WristExposure = -5.0,

  # Must equal the server --port and both sides of the SSH -L forwarding rule.
  [int]$PolicyPort = 8765,

  # Per-command safety limit in degrees. Keep 2 for the first real motions.
  # Do not increase this simply to make an incorrect policy move faster.
  [double]$MaxStepDeg = 2.0,

  # At 15 Hz, 20 steps is about 1.3 seconds of commanded motion.
  # Raise only after dry run and short live motion have been verified.
  [int]$MaxSteps = 2000,

  # Sends one observation for a server/CUDA warmup, but never executes it.
  # Normally leave this at 1. Set 0 only to diagnose WebSocket connectivity.
  [int]$WarmupInfers = 1,

  # Cold G0.5 inference may take tens of seconds; 120 s avoids a false timeout.
  [double]$TimeoutS = 120,

  # The script is dry-run by default. This explicit switch is required before
  # any G0.5 target is allowed to reach COM24.
  [switch]$DisableMotion,

  # Your OpenCV build has no GUI backend. Keep this off unless a GUI-enabled
  # OpenCV build is installed; pass -Display to request camera windows.
  [switch]$Display,

  # Optional: save exactly what is sent to G0.5 plus its 256x256 server-input
  # preview. Example: -DumpObservationDir .\outputs\g05_input_check
  [string]$DumpObservationDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python = "C:\Users\19142\.conda\envs\lerobot\python.exe"
$Client = Join-Path $PSScriptRoot "g05_so101_policy_client.py"

if (-not (Test-Path -LiteralPath $Python)) {
  throw "LeRobot Python is missing: $Python"
}

$ClientArgs = @(
  $Client,
  "--host", "127.0.0.1",
  "--port", "$PolicyPort",
  "--task", $Task,
  "--robot-port", "COM24",
  "--robot-id", "fenghao_so101_follower",
  "--fixed-camera", "$FixedCameraIndex",
  "--wrist-camera", "$WristCameraIndex",
  "--fixed-crop-right-px", "$FixedCropRightPx",
  "--wrist-crop-right-px", "$WristCropRightPx",
  "--camera-fps", "15",
  "--fixed-exposure", "$FixedExposure",
  "--wrist-exposure", "$WristExposure",
  "--action-fps", "15",
  "--max-step-deg", "$MaxStepDeg",
  "--max-steps", "$MaxSteps",
  "--warmup-infers", "$WarmupInfers",
  "--timeout-s", "$TimeoutS"
)

if ($DumpObservationDir) {
  $ClientArgs += @("--dump-observation-dir", $DumpObservationDir)
}

if ($DisableMotion) {
  $ClientArgs += "--dry-run"
  Write-Warning "DRY RUN: no G0.5 action will be sent to COM24. Add -EnableMotion only after a successful dry run."
} else {
  Write-Warning "LIVE MOTION ENABLED. Clear the desk and keep the robot power switch within reach."
}
if (-not $Display) {
  $ClientArgs += "--no-display"
}

Write-Host "G0.5 SO101 client"
Write-Host "  task:    $Task"
Write-Host "  policy:  ws://127.0.0.1:$PolicyPort"
Write-Host "  cameras: exterior=$FixedCameraIndex, wrist_right=$WristCameraIndex"
Write-Host "  image:   exterior crop right $FixedCropRightPx px -> $([int](640 - $FixedCropRightPx))x480; wrist crop right $WristCropRightPx px -> $([int](640 - $WristCropRightPx))x480"
Write-Host "  exposure: exterior=$FixedExposure; wrist_right=$WristExposure"
Write-Host "  timeout: $TimeoutS s; warmup: $WarmupInfers; max steps: $MaxSteps; max step: $MaxStepDeg deg"
Write-Host "  display: $Display"

& $Python @ClientArgs
exit $LASTEXITCODE


# check camera
# .\scripts\g0.5\run_g05_so101_client.ps1 `
#   -Task "pick up the white block" `
#   -DumpObservationDir .\outputs\g05_input_check

# run
# .\scripts\g0.5\run_g05_so101_client.ps1 `
#    -Task "pick up the white block" `
#    -EnableMotion
