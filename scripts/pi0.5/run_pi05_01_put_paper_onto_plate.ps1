param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000,
  [switch]$DryRun,
  [int]$MaxSteps = 1000,
  [int]$ReplanEvery = 10,
  [double]$MaxRelativeTarget = 4.0,
  [int]$WarmupInfers = 2,
  [switch]$Record,
  [string]$RecordDir = "D:\workspace\Manipulation\so101\so101_policy_runs",
  [switch]$RecordStepState
)

$ErrorActionPreference = "Stop"

& "$PSScriptRoot\run_pi05_so101_policy.ps1" `
  -HostAddress $HostAddress `
  -Port $Port `
  -Prompt "put the white toilet paper roll onto the plate" `
  -MaxSteps $MaxSteps `
  -ReplanEvery $ReplanEvery `
  -MaxRelativeTarget $MaxRelativeTarget `
  -WarmupInfers $WarmupInfers `
  -DryRun:$DryRun `
  -Record:$Record `
  -RecordDir $RecordDir `
  -RecordStepState:$RecordStepState
