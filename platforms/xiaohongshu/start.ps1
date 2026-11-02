[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Install,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"

Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PythonLauncher) {
        & $PythonLauncher.Source -3 -m venv .venv
    } else {
        $PythonCommand = Get-Command python -ErrorAction Stop
        & $PythonCommand.Source -m venv .venv
    }
    $Install = $true
}

if ($Install) {
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r $Requirements
}

$PortOwner = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($PortOwner) {
    throw "Port $Port is already used by process $($PortOwner.OwningProcess). Try .\start.ps1 -Port 8001."
}

$env:XHS_API_HOST = "127.0.0.1"
$env:XHS_API_PORT = [string]$Port
$LocalUrl = "http://127.0.0.1:$Port/"

Write-Host "Starting XHS Collector" -ForegroundColor Cyan
Write-Host "Workbench: $LocalUrl"
Write-Host "API docs: ${LocalUrl}docs"
Write-Host "Press Ctrl+C to stop the service."

if ($OpenBrowser) {
    $OpenCommand = "Start-Sleep -Seconds 2; Start-Process '$LocalUrl'"
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", $OpenCommand
}

& $VenvPython (Join-Path $ProjectRoot "main.py")
