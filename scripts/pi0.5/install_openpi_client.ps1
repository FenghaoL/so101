$ErrorActionPreference = "Stop"

$openpiClient = "D:\workspace\Manipulation\openpi\packages\openpi-client"

if (-not (Test-Path $openpiClient)) {
  throw "Cannot find openpi-client at $openpiClient"
}

Write-Host "Installing lightweight openpi-client into the current Python environment..."
Write-Host "Path: $openpiClient"
python -m pip install -e $openpiClient
