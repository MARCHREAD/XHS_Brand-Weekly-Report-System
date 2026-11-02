[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$MainScript = (Join-Path $ProjectRoot "main.py").ToLowerInvariant()
$Listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)

if (-not $Listeners) {
    Write-Host "No service is listening on port $Port."
    exit 0
}

$Stopped = 0
foreach ($Listener in $Listeners) {
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Listener.OwningProcess)"
    $CommandLine = [string]$Process.CommandLine
    if (-not $CommandLine.ToLowerInvariant().Contains($MainScript)) {
        throw "Port $Port belongs to process $($Listener.OwningProcess), which is not this XHS Collector. It was not stopped."
    }
    Stop-Process -Id $Listener.OwningProcess
    $Stopped++
}

Write-Host "Stopped XHS Collector process count: $Stopped"

