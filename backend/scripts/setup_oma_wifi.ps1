# One-command Wi-Fi setup for OMA SigLIP2 Android demo (Windows PowerShell 5.1+)
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\backend\scripts\setup_oma_wifi.ps1
# LAN only. Never port-forward this unauthenticated demo server.
[CmdletBinding()]
param([int]$InterfaceIndex = 0, [int]$Port = 8765, [switch]$ConfigureFirewall, [switch]$MakePrivate)
$ErrorActionPreference = "Stop"
$ruleName = "OMA-Visual-WiFi-$Port"

function Find-OmaWifi {
    param([int]$PreferredInterfaceIndex)
    $all = @(Get-NetIPConfiguration | Where-Object {
        $null -ne $_.IPv4Address -and $null -ne $_.NetAdapter -and $_.NetAdapter.Status -eq "Up"
    })
    if ($PreferredInterfaceIndex -gt 0) {
        $picked = @($all | Where-Object { $_.InterfaceIndex -eq $PreferredInterfaceIndex })
        if ($picked.Count -ne 1) { throw "Wi-Fi adapter index $PreferredInterfaceIndex is not connected" }
        return $picked[0]
    }
    $wifi = @($all | Where-Object {
        $_.InterfaceAlias -match '(?i)wi.?fi|wireless|wlan|беспровод' -or
        $_.NetAdapter.InterfaceDescription -match '(?i)wi.?fi|wireless|802\.11|wlan|беспровод'
    })
    if ($wifi.Count -ne 1) {
        $candidates = $all | ForEach-Object {
            "$($_.InterfaceIndex) $($_.InterfaceAlias) $($_.IPv4Address[0].IPAddress)"
        }
        throw "Cannot uniquely select connected Wi-Fi. Active adapters: $($candidates -join '; ')"
    }
    return $wifi[0]
}

function Configure-OmaFirewall {
    param($Wifi, [int]$ListenPort, [bool]$TrustThisNetwork)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Administrator permission required for Windows Firewall"
    }
    $idx = [int]$Wifi.InterfaceIndex
    $profile = Get-NetConnectionProfile -InterfaceIndex $idx
    if ($profile.NetworkCategory -ne "Private") {
        if (-not $TrustThisNetwork) { throw "Network not Private; refusing inbound access" }
        Set-NetConnectionProfile -InterfaceIndex $idx -NetworkCategory Private
        $profile = Get-NetConnectionProfile -InterfaceIndex $idx
        if ($profile.NetworkCategory -ne "Private") {
            throw "Could not switch trusted Wi-Fi to Private profile"
        }
    }
    $localIP = [string]$Wifi.IPv4Address[0].IPAddress
    $adapterName = [string]$Wifi.InterfaceAlias
    Get-NetFirewallRule -Name "OMA-Visual-WiFi-$ListenPort" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction Stop
    New-NetFirewallRule -Name "OMA-Visual-WiFi-$ListenPort" -DisplayName "OMA SigLIP2 demo - trusted Wi-Fi only" -Direction Inbound -Action Allow -Enabled True -Protocol TCP -LocalPort $ListenPort -LocalAddress $localIP -RemoteAddress LocalSubnet -InterfaceAlias $adapterName -Profile Private | Out-Null
    Write-Host "Windows Firewall configured: Wi-Fi $adapterName ($localIP) port $ListenPort, local subnet only."
}

if ($Port -lt 1024 -or $Port -gt 65535) { throw "Invalid port (1024..65535)" }
$wifi = Find-OmaWifi -PreferredInterfaceIndex $InterfaceIndex
$ip = [string]$wifi.IPv4Address[0].IPAddress
$index = [int]$wifi.InterfaceIndex
$alias = [string]$wifi.InterfaceAlias
$profile = Get-NetConnectionProfile -InterfaceIndex $index -ErrorAction Stop

if ($ConfigureFirewall) {
    Configure-OmaFirewall -Wifi $wifi -ListenPort $Port -TrustThisNetwork:$MakePrivate
    exit 0
}

Write-Host ""
Write-Host "OMA Wi-Fi demo setup" -ForegroundColor Cyan
Write-Host "Active Wi-Fi: $alias"
Write-Host "Laptop IPv4: $ip"
Write-Host "Network profile: $($profile.NetworkCategory)"

$makePrivateNetwork = $false
if ($profile.NetworkCategory -ne "Private") {
    Write-Warning "This Wi-Fi is PUBLIC. Do not expose an unauthenticated demo server on untrusted networks."
    $answer = Read-Host "Is this your trusted own Wi-Fi or private hotspot? Type YES to set Private"
    if ($answer -cne "YES") { throw "Not authorized to expose this demo API on the current Wi-Fi" }
    $makePrivateNetwork = $true
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Configure-OmaFirewall -Wifi $wifi -ListenPort $Port -TrustThisNetwork:$makePrivateNetwork
} else {
    Write-Host "Approve the Windows Administrator prompt to configure scoped Wi-Fi access."
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        ('"' + $PSCommandPath + '"'), "-InterfaceIndex", "$index", "-Port", "$Port", "-ConfigureFirewall"
    )
    if ($makePrivateNetwork) { $arguments += "-MakePrivate" }
    $adminPowerShell = Join-Path $PSHOME "powershell.exe"
    $child = Start-Process -FilePath $adminPowerShell -ArgumentList $arguments -Verb RunAs -PassThru -Wait
    if ($child.ExitCode -ne 0) {
        throw "Firewall setup failed or admin consent denied"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$python = Join-Path $repoRoot ".venv-vision\Scripts\python.exe"
$apiScript = Join-Path $PSScriptRoot "serve_partial_visual_api.py"
if (-not (Test-Path $python)) { throw "Python virtual environment not found: $python" }
if (-not (Test-Path $apiScript)) { throw "SigLIP2 API script not found: $apiScript" }

$statusUrl = "http://127.0.0.1:$Port/api/v1/visual-search/status"
$status = $null
try {
    $status = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 3
} catch {
    Write-Host "Starting local SigLIP2 server in another window..."
    $argsPython = ('"' + $apiScript + '" --host ' + $ip + ' --port ' + $Port)
    $server = Start-Process -FilePath $python -ArgumentList $argsPython -WorkingDirectory $repoRoot -PassThru
    for ($attempt = 1; $attempt -le 25; $attempt++) {
        Start-Sleep -Milliseconds 800
        if ($server.HasExited) {
            throw "Python server exited. Check its window; exit code $($server.ExitCode)"
        }
        try {
            $status = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 2
            break
        } catch { }
    }
}
if ($null -eq $status -or -not $status.ready) {
    throw "SigLIP2 server did not report ready=true. Inspect the Python window."
}

$networkUrl = "http://$ip" + ":$Port"
try {
    $remote = Invoke-RestMethod -Uri "$networkUrl/api/v1/visual-search/status" -TimeoutSec 5
    if (-not $remote.ready) { throw "ready=false" }
} catch {
    throw "Server responds on localhost but not Wi-Fi. Stop old server using Ctrl+C and rerun setup."
}

Write-Host ""
Write-Host "SUCCESS: OMA SigLIP2 is accessible on laptop Wi-Fi." -ForegroundColor Green
Write-Host "Indexed SKUs: $($status.indexed_products) / $($status.catalog_products)"
Write-Host "Paste this into OMA Android photo-search settings:"
Write-Host $networkUrl -ForegroundColor Cyan
Write-Host "Open this link on the PHONE to check actual phone-to-laptop connectivity:"
Write-Host "$networkUrl/api/v1/visual-search/status" -ForegroundColor Cyan
Write-Host "Both devices must use the same trusted Wi-Fi, without client isolation."
Write-Host "Never port-forward $Port to the internet. Stop the Python server after testing."
