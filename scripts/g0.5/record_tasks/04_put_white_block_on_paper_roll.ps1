# # Record 30 square-camera demonstrations. Run this file with no parameters.
# $ErrorActionPreference = "Stop"

# $recorder = Join-Path $PSScriptRoot "..\record_g05_so101.ps1"
# & $recorder `
#   -Task "Put the white block on the paper roll." `
#   -Episodes 30 `
#   -DatasetGroup "so101_g05_square_v1" `
#   -TaskFolder "04_put_white_block_on_paper_roll" `
#   -DisplayData

# exit $LASTEXITCODE


.\scripts\g0.5\record_g05_so101.ps1 `
  -Task "Put the white block on the paper roll." `
  -Episodes 30 `
  -DatasetGroup "so101_g05_square_v1" `
  -TaskFolder "04_put_white_block_on_paper_roll" `
  -DisplayData