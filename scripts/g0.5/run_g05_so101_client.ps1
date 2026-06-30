[CmdletBinding()]
param(
  # G0.5 SO101 policy prompts should be concise English instructions.
  [string]$Task = "pick up the white block",
  # Other prompts to try, one task per run:
  # "put the red block into the blue bowl"
  # "move the wooden cube to the right"
  # "pick up the yellow screwdriver"

  # Physical devices on this laptop.  The model names are fixed by the client:
  # camera 2 -> exterior, camera 0 -> wrist_right.
  [int]$FixedCameraIndex = 2,
  [int]$WristCameraIndex = 0,

  # Only the exterior view is cropped.  Removing its rightmost 160 pixels
  # converts native 640x480 into the square 480x480 G0.5 image. The wrist
  # frame remains its whole 640x480 image.
  [int]$FixedCropRightPx = 160,
  [int]$WristCropRightPx = 0,

  # UVC/DirectShow settings, applied as each camera opens.  0.25 requests
  # manual exposure mode for common Windows camera drivers; -6 is the driver's
  # exposure value, not milliseconds.  Change these at the top of this command
  # or pass values on the command line while using the dashboard to inspect it.
  [double]$FixedAutoExposure = 0.25,
  [double]$WristAutoExposure = 0.25,
  [double]$FixedExposure = -6.0,
  [double]$WristExposure = -6.0,
  [int]$CameraFps = 30,

  # Local endpoint of the SSH tunnel.  The remote server itself listens on
  # 127.0.0.1:8765, so its tunnel must forward local port 8765 to it.
  [int]$PolicyPort = 8765,

  # Official Galaxea SO100 client defaults.
  [double]$ActionFps = 15.0,
  [double]$MaxStepDeg = 10.0,
  [int]$ExpectedActionSteps = 32,
  [int]$MaxSteps = 0,       # 0 = run until Stop is pressed.
  [int]$WarmupInfers = 0,  # Optional CUDA warmup; never moves the arm.
  [double]$TimeoutS = 120.0,

  # Temporary run-only calibration probes.  They affect both the state sent to
  # G0.5 and the inverse transform back to the robot; they do not edit LeRobot
  # calibration files or dataset files.
  [double[]]$JointOffsets = @(0, 0, 0, 0, 0, 0),
  [double[]]$JointScales = @(1, 1, 1, 1, 1, 1),

  # Dashboard retains all cards by default (0). Use a finite number to cap RAM
  # on very long runs. -NoDashboard provides a compact terminal-only loop.
  [switch]$NoDashboard,
  [int]$DashboardFps = 15,
  [int]$DashboardCameraFps = 10,
  [int]$DashboardHistory = 0,
  [string]$TimingLog = "",
  # Print every decoded inbound WebSocket packet verbatim: handshake, reset,
  # optional warmup, and every policy/cache response. Set to $false only when
  # the terminal volume is undesirable.
  [bool]$PrintServerResponses = $true,
  [string]$DumpObservationDir = "",

  # Keep live hardware motion opt-in. -DisableMotion is accepted for older
  # commands but is redundant because dry-run is already the default.
  [switch]$EnableMotion,
  [switch]$DisableMotion,
  [switch]$NoHome,

  # The recovered OpenCV installation is headless, so this runner deliberately
  # uses the Tk dashboard rather than trying to open cv2.imshow windows.
  [switch]$Display
)

$ErrorActionPreference = "Stop"
$Python = "C:\Users\19142\.conda\envs\lerobot\python.exe"
$Client = Join-Path $PSScriptRoot "g05_so101_policy_client.py"

if (-not (Test-Path -LiteralPath $Python)) {
  throw "LeRobot Python is missing: $Python"
}
if ($EnableMotion -and $DisableMotion) {
  throw "-EnableMotion and -DisableMotion cannot be used together."
}
if ($Display) {
  throw "This laptop's OpenCV build has no reliable GUI backend. Use the default dashboard instead of -Display."
}
if ($JointOffsets.Count -ne 6 -or $JointScales.Count -ne 6) {
  throw "JointOffsets and JointScales must each contain exactly six values in SO101 order: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper."
}
if ($JointScales | Where-Object { $_ -le 0 }) {
  throw "Every JointScales entry must be positive."
}
if ($FixedCropRightPx -lt 0 -or $FixedCropRightPx -ge 640 -or $WristCropRightPx -lt 0 -or $WristCropRightPx -ge 640) {
  throw "Crop values must be in [0, 639]."
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
  "--camera-fps", "$CameraFps",
  "--fixed-auto-exposure", "$FixedAutoExposure",
  "--wrist-auto-exposure", "$WristAutoExposure",
  "--fixed-exposure", "$FixedExposure",
  "--wrist-exposure", "$WristExposure",
  "--action-fps", "$ActionFps",
  "--max-step-deg", "$MaxStepDeg",
  "--expected-action-steps", "$ExpectedActionSteps",
  "--max-steps", "$MaxSteps",
  "--warmup-infers", "$WarmupInfers",
  "--timeout-s", "$TimeoutS",
  "--dashboard-fps", "$DashboardFps",
  "--dashboard-camera-fps", "$DashboardCameraFps",
  "--dashboard-history", "$DashboardHistory",
  "--joint-offsets"
)
foreach ($value in $JointOffsets) {
  $ClientArgs += "$value"
}
$ClientArgs += "--joint-scales"
foreach ($value in $JointScales) {
  $ClientArgs += "$value"
}

if (-not $NoDashboard) {
  $ClientArgs += "--dashboard"
}
if ($TimingLog) {
  $ClientArgs += @("--timing-log", $TimingLog)
}
if ($PrintServerResponses) {
  $ClientArgs += "--print-server-responses"
}
if ($DumpObservationDir) {
  $ClientArgs += @("--dump-observation-dir", $DumpObservationDir)
}

if ($EnableMotion) {
  Write-Warning "LIVE MOTION ENABLED. Clear the desk and keep the robot power switch within reach."
  if (-not $NoHome) {
    $null = Read-Host "Workspace clear? Press Enter to connect and move to the official G0.5 training-mean home pose"
    $ClientArgs += "--home-to-training-mean"
  } else {
    $null = Read-Host "Workspace clear? Press Enter to connect without automatic home motion"
  }
} else {
  $ClientArgs += "--dry-run"
  Write-Warning "DRY RUN: policy targets are displayed but never sent to COM24. Add -EnableMotion only after checking the dashboard."
}

Write-Host "G0.5 SO101 client"
Write-Host "  task:       $Task"
Write-Host "  policy:     ws://127.0.0.1:$PolicyPort"
Write-Host "  cameras:    exterior=$FixedCameraIndex, wrist_right=$WristCameraIndex"
Write-Host "  outbound:   exterior $(640 - $FixedCropRightPx)x480 after right crop; wrist_right $(640 - $WristCropRightPx)x480 whole frame"
Write-Host "  exposure:   exterior auto=$FixedAutoExposure value=$FixedExposure; wrist_right auto=$WristAutoExposure value=$WristExposure"
Write-Host "  official:   action=$ActionFps Hz; server chunk=$ExpectedActionSteps; step cap=$MaxStepDeg deg"
Write-Host "  dashboard:  $(-not $NoDashboard); UI=$DashboardFps Hz, camera=$DashboardCameraFps Hz, history=$DashboardHistory (0 means retain all cards)"
Write-Host "  motion:     $EnableMotion; automatic home=$($EnableMotion -and -not $NoHome)"
Write-Host "  server packets: print decoded full inbound packets = $PrintServerResponses"

& $Python @ClientArgs
exit $LASTEXITCODE


# Dry run with live model-input dashboard:
# .\scripts\g0.5\run_g05_so101_client.ps1 -Task "pick up the white block"
#
# Live run using official 15 Hz / 32 actions / 10 degree cap defaults:
# .\scripts\g0.5\run_g05_so101_client.ps1 -Task "pick up the white block" -EnableMotion
#
# Inspect the exact outbound images and log each client timing event:
# .\scripts\g0.5\run_g05_so101_client.ps1 `
#   -Task "pick up the white block" `
#   -DumpObservationDir .\outputs\g05_input_check `
#   -TimingLog .\outputs\g05_timing.jsonl
