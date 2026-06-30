# # Record 30 square-camera demonstrations. Run this file with no parameters.
# $ErrorActionPreference = "Stop"

# $recorder = Join-Path $PSScriptRoot "..\record_g05_so101.ps1"
# & $recorder `
#   -Task "Pick up the white block." `
#   -Episodes 30 `
#   -DatasetGroup "so101_g05_square_v1" `
#   -TaskFolder "01_pick_up_white_block" `
#   -DisplayData

# exit $LASTEXITCODE



.\scripts\g0.5\record_g05_so101.ps1 `
  -Task "Pick up the white block." `
  -Episodes 30 `
  -DatasetGroup "so101_g05_square_v1" `
  -TaskFolder "01_pick_up_white_block" `
  -DisplayData
