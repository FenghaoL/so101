# Record 30 square-camera demonstrations. Run this file with no parameters.
$ErrorActionPreference = "Stop"

$recorder = Join-Path $PSScriptRoot "..\record_g05_so101.ps1"
& $recorder `
  -Task "Put the paper roll on the pink bowl." `
  -Episodes 30 `
  -DatasetGroup "so101_g05_square_v1" `
  -TaskFolder "03_put_paper_roll_on_pink_bowl" `
  -DisplayData
  
exit $LASTEXITCODE
