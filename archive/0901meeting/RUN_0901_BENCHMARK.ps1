param(
    [int]$Samples = 30
)

$ErrorActionPreference = "Stop"

$MeetingRoot = $PSScriptRoot
$MainRoot = Split-Path $MeetingRoot -Parent
$Python = (Join-Path $MainRoot "..\hyberik\venv\Scripts\python.exe")
if (-not (Test-Path $Python)) {
    $Python = "d:\School\Projects\hyberik\venv\Scripts\python.exe"
}

$Script = Join-Path $MeetingRoot "benchmark.py"

Write-Host "=================================================="
Write-Host " 🚀 Running 0901 Meeting Benchmark on RTX 3090"
Write-Host "=================================================="
Write-Host "Python:  $Python"
Write-Host "Script:  $Script"
Write-Host "Samples: $Samples"

& $Python $Script --samples $Samples
