param(
  [Parameter(Mandatory=$true)]
  [string]$HostAddress,

  [int]$Port = 8000,

  [Parameter(Mandatory=$true)]
  [string]$Prompt,

  [switch]$DryRun,
  [int]$MaxSteps = 360,
  [int]$ReplanEvery = 4,
  [double]$MaxRelativeTarget = 8.0,
  [int]$WarmupInfers = 2,
  [switch]$Record,
  [string]$RecordDir = "D:\workspace\Manipulation\so101\so101_policy_runs",
  [switch]$RecordStepState
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$openpiRoot = "D:\workspace\Manipulation\openpi"

Write-Host "SO101 pi0.5 local policy runner"
Write-Host "--------------------------------"
Write-Host "Policy server:      $HostAddress`:$Port"
Write-Host "Prompt:             $Prompt"
Write-Host "Robot port:         COM24"
Write-Host "Cameras:            fixed=2 wrist=0, 640x480 @ 20fps"
Write-Host "Exposure:           fixed=-5 wrist=-5"
Write-Host "Control Hz:         18"
Write-Host "Replan every:       $ReplanEvery step(s)"
Write-Host "Warmup infers:      $WarmupInfers"
Write-Host "Max relative target $MaxRelativeTarget"
Write-Host "Dry run:            $DryRun"
Write-Host "Record:             $Record"
if ($Record) {
  Write-Host "Record dir:         $RecordDir"
  Write-Host "Record step state:  $RecordStepState"
}
Write-Host ""

$argsList = @(
  "$repoRoot\scripts\run_pi05_so101_policy.py",
  "--host", $HostAddress,
  "--port", "$Port",
  "--prompt", $Prompt,
  "--openpi-root", $openpiRoot,
  "--max-steps", "$MaxSteps",
  "--replan-every", "$ReplanEvery",
  "--max-relative-target", "$MaxRelativeTarget",
  "--warmup-infers", "$WarmupInfers"
)

if ($DryRun) {
  $argsList += "--dry-run"
}
if ($Record) {
  $argsList += @("--record", "--record-dir", $RecordDir)
}
if ($RecordStepState) {
  $argsList += "--record-step-state"
}

python @argsList

# .\scripts\run_pi05_so101_policy.ps1 `
#   -HostAddress 127.0.0.1 `
#   -Port 8000 `
#   -Prompt "put the yellow screwdriver onto the plate" `
#   -DryRun `
#   -MaxSteps 30


# ssh -N -L 8000:127.0.0.1:8000 fenghao@chickadee.engin.umich.edu