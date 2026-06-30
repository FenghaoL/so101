[CmdletBinding()]
param(
  [string]$LabelsRoot = "D:\workspace\Manipulation\so101\so101_data\g05_rl_raw\so101_g05_rl_pick_white_v1",
  [string]$Output = "",
  [int]$MaxPairsPerBucket = 20,
  [string]$DatasetDirOverride = "",
  [string]$Python = "C:\Users\19142\.conda\envs\g05-record-v3\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python)) {
  throw "Python is missing: $Python"
}
if (-not (Test-Path -LiteralPath $LabelsRoot)) {
  throw "LabelsRoot does not exist: $LabelsRoot"
}
if ($Output.Length -eq 0) {
  $Output = Join-Path $LabelsRoot "pairs.jsonl"
}

$builder = Join-Path $PSScriptRoot "build_rl_pairs.py"
if (-not (Test-Path -LiteralPath $builder)) {
  throw "Pair builder is missing: $builder"
}

$argsList = @(
  $builder,
  "--labels-root", $LabelsRoot,
  "--output", $Output,
  "--max-pairs-per-bucket", "$MaxPairsPerBucket"
)
if ($DatasetDirOverride.Length -gt 0) {
  $argsList += @("--dataset-dir-override", $DatasetDirOverride)
}

Write-Host "Building G0.5 RL trajectory pairs"
Write-Host "  labels root: $LabelsRoot"
Write-Host "  output:      $Output"
Write-Host "  max/bucket:  $MaxPairsPerBucket"
if ($DatasetDirOverride.Length -gt 0) {
  Write-Host "  dataset dir override: $DatasetDirOverride"
}

& $Python @argsList
exit $LASTEXITCODE
