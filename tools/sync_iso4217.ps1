# PowerShell wrapper for tools/sync_iso4217.py
#
# Usage:
#   .\tools\sync_iso4217.ps1                 # refresh catalog from SIX
#   .\tools\sync_iso4217.ps1 -DryRun         # dry-run, log diff only
#
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "venv python not found at $venvPython - activate or create the venv first"
    exit 1
}

$scriptPath = Join-Path $PSScriptRoot "sync_iso4217.py"
$pyArgs = @($scriptPath)
if ($DryRun) { $pyArgs += "--dry-run" }

& $venvPython @pyArgs
exit $LASTEXITCODE
