# Connect a USB-debugged Android phone directly to the local OMA photo search.
# No Wi-Fi, router, VPN or internet-facing tunnel is required.
param([string]$Serial = "")
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$toolsRoot = Split-Path $repoRoot -Parent
$adbPath = Join-Path $toolsRoot "platform-tools/adb.exe"
if (-not (Test-Path $adbPath)) {
    $found = Get-Command adb.exe -ErrorAction SilentlyContinue
    if ($found) { $adbPath = $found.Source }
}
if (-not (Test-Path $adbPath)) {
    Write-Host "ADB not found. Downloading official Google Platform Tools..."
    $zip = Join-Path $env:TEMP "oma-platform-tools.zip"
    Invoke-WebRequest -Uri "https://dl.google.com/android/repository/platform-tools-latest-windows.zip" -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $toolsRoot -Force
    Remove-Item $zip
    $adbPath = Join-Path $toolsRoot "platform-tools/adb.exe"
}
if (-not (Test-Path $adbPath)) { throw "ADB missing. Download Android Platform Tools from developer.android.com/tools/releases/platform-tools" }

try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/v1/visual-search/status" -TimeoutSec 6
    if (-not $status.ready) { throw "Image-search server says ready=false" }
    Write-Host "SigLIP2 local server: $($status.indexed_products) indexed SKU."
} catch {
    throw "Start server first: .\.venv-vision\Scripts\python.exe .\backend\scripts\serve_partial_visual_api.py"
}

Write-Host "Connecting to Android over USB. Enable Developer options > USB debugging and approve the PC on your phone."
& $adbPath start-server | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Could not start ADB" }
$deviceLines = @(& $adbPath devices)
$ready = @($deviceLines | Where-Object { $_ -match '^([^\s]+)\s+device$' } | ForEach-Object { ($_ -split '\s+')[0] })
if ($Serial) {
    if ($ready -notcontains $Serial) { throw "Device $Serial not authorized. ADB output: $($deviceLines -join '; ')" }
    $device = $Serial
} elseif ($ready.Count -eq 1) {
    $device = $ready[0]
} elseif ($ready.Count -eq 0) {
    throw "No authorized Android device detected. Unlock phone, allow USB debugging on it, and reconnect the USB cable. ADB: $($deviceLines -join '; ')"
} else {
    throw "Several Android devices detected: $($ready -join ', '). Run with -Serial DEVICE_ID for each phone."
}
& $adbPath -s $device reverse tcp:8765 tcp:8765
if ($LASTEXITCODE -ne 0) { throw "USB tunnel failed" }
Write-Host ""
Write-Host "SUCCESS: USB link for Android $device is active." -ForegroundColor Green
Write-Host "In OMA APK > Search by photo > Configure PC photo search, enter:"
Write-Host "http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "Keep USB cable connected and keep the SigLIP2 server running on your PC."
Write-Host "If the connection is interrupted, rerun this script."
