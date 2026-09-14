param(
    [string]$InputNpz = "",
    [int]$MaxFrames = 0,
    [switch]$NoRender,
    [int]$ImageSize = 512
)

$ErrorActionPreference = "Stop"

$MeetingRoot = $PSScriptRoot
$MainRoot = Split-Path $MeetingRoot -Parent
$Python = (Join-Path $MainRoot "..\hyberik\venv\Scripts\python.exe")
if (-not (Test-Path $Python)) {
    $Python = "d:\School\Projects\hyberik\venv\Scripts\python.exe"
}

$Script = Join-Path $MeetingRoot "run_best_pipeline.py"
if (-not $InputNpz) {
    $InputNpz = Join-Path $MainRoot "data\amass_dataset\punching_poses.npz"
}

$ArgsList = @(
    $Script,
    "--input", $InputNpz,
    "--max_frames", "$MaxFrames",
    "--image_size", "$ImageSize"
)

if ($NoRender) {
    $ArgsList += "--no_render"
}

Write-Host "=================================================="
Write-Host " 🚀 Running 0901 Best Method Pipeline (Full Sequence)"
Write-Host "=================================================="
Write-Host "Python:     $Python"
Write-Host "Input:      $InputNpz"
Write-Host "Max Frames: $(if ($MaxFrames -eq 0) { 'ALL (Full Sequence)' } else { $MaxFrames })"
Write-Host "Image Size: $ImageSize x $ImageSize (Front-Facing Upright)"

& $Python @ArgsList
