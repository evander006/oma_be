# Run from PowerShell on the Windows PC with an NVIDIA GPU.
# The full-index run can be safely restarted; already encoded SKUs are reused.
param(
    [string]$Catalog = "",
    [string]$Output = "",
    [int]$BatchSize = 12,
    [double]$RequestDelay = 0.15,
    [switch]$AllowCpu
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
if ([string]::IsNullOrWhiteSpace($Catalog)) {
    $Catalog = Join-Path $repoRoot "../oma_front/android_companion/app/src/main/assets/embedded_catalog.db.bin"
}
if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $repoRoot "backend/data/visual_index"
}
if (-not (Test-Path $Catalog)) {
    throw "Cannot locate OMA catalogue: $Catalog. Clone oma_front next to oma_be or use -Catalog."
}
if ($BatchSize -lt 1 -or $BatchSize -gt 64) {
    throw "BatchSize must be between 1 and 64"
}
if ($RequestDelay -lt 0) {
    throw "RequestDelay must be non-negative"
}

$venv = Join-Path $repoRoot ".venv-vision"
$python = Join-Path $venv "Scripts/python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating Python virtual environment for visual search..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $venv
    } else {
        & python -m venv $venv
    }
    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed" }
}
Write-Host "Installing visual-model requirements..."
& $python -m pip install -r (Join-Path $repoRoot "backend/requirements-visual-index.txt")
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed" }

$hardware = & $python -c "import torch; print('CUDA' if torch.cuda.is_available() else 'CPU')"
if ($LASTEXITCODE -ne 0) { throw "Cannot import torch" }
Write-Host "Available inference device: $hardware"
if ($hardware -notmatch "CUDA" -and -not $AllowCpu) {
    throw ("CUDA was not detected. Install the correct NVIDIA PyTorch CUDA wheel " +
        "in $venv or explicitly run with -AllowCpu (much slower).")
}
$env:HF_HUB_DISABLE_TELEMETRY = "1"
Write-Host "Encoding OMA catalogue. Interrupt/restart safely with identical arguments."
Write-Host "Output: $Output"
& $python (Join-Path $repoRoot "backend/scripts/build_full_visual_index.py") `
    $Catalog --output $Output --batch-size $BatchSize --request-delay $RequestDelay
if ($LASTEXITCODE -ne 0) { throw "Visual index build did not complete" }

$manifestPath = Join-Path $Output "manifest.json"
if (-not (Test-Path $manifestPath)) { throw "No index manifest was written" }
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
if (-not $manifest.complete) {
    throw "Index is incomplete: $($manifest.indexed_count)/$($manifest.catalog_count). Check failed photo URLs, then rerun."
}
Write-Host "READY: $($manifest.indexed_count) real SKU images indexed."
Write-Host "Configure OMA_VISUAL_INDEX_DIR=$Output on the backend host and install the same model runtime there."
Write-Host "Before rollout, evaluate with independent, labelled phone photos."
