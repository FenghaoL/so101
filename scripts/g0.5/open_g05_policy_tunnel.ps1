[CmdletBinding()]
param(
  [string]$Server = "chickadee.engin.umich.edu",
  [string]$User = "fenghao",
  [int]$LocalPort = 8765,
  [int]$RemotePort = 8765
)

$ErrorActionPreference = "Stop"
$Forward = "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}"

Write-Host "Forwarding ws://127.0.0.1:$LocalPort to ${User}@${Server}:127.0.0.1:$RemotePort"
Write-Host "Keep this window open while the SO101 client is running. Ctrl+C closes the tunnel."

& ssh -N `
  -o ExitOnForwardFailure=yes `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  -L $Forward `
  "${User}@${Server}"

exit $LASTEXITCODE


# ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 fenghao@chickadee.engin.umich.edu