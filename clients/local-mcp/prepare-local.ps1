# SPDX-License-Identifier: LGPL-3.0-or-later
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$Bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Bundle '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
  py -3.12 -m venv $Venv
}
& $Python -m pip install --require-hashes --only-binary=:all: -r (Join-Path $Bundle 'requirements.lock')
if (-not (Test-Path -LiteralPath (Join-Path $Bundle 'config.json'))) {
  Copy-Item -LiteralPath (Join-Path $Bundle 'config.example.json') -Destination (Join-Path $Bundle 'config.json')
}
Write-Host 'Prepared without pairing or persistence. Review config.json before use.'
