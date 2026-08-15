param(
  [ValidateSet('choose-root','pair','connect','revoke-local')]
  [string]$Action = 'connect',
  [string]$Code = ''
)
$ErrorActionPreference = 'Stop'
$Bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Bundle '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
  throw 'Ambiente non preparato. Leggi README.md; nessuna installazione automatica viene eseguita.'
}
$Args = @('-m','r740_local_mcp.cli','--config',(Join-Path $Bundle 'config.json'),$Action)
if ($Action -eq 'pair') {
  if ([string]::IsNullOrWhiteSpace($Code)) { throw 'Fornire -Code ottenuto dal portale.' }
  $Args += @('--code',$Code)
}
& $Python @Args
