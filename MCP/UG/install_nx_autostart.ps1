[CmdletBinding()]
param(
    [string]$NXRoot = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$userRoot = Join-Path $root "nx_user"
$startup = Join-Path $userRoot "startup"
$source = Join-Path $root "dotnet_bridge\bin\NXMcPRemotingServer.dll"
$target = Join-Path $startup "NXMcPRemotingServer.dll"
$build = Join-Path $root "dotnet_bridge\build_bridge.ps1"

if (-not $NXRoot) {
    $NXRoot = [Environment]::GetEnvironmentVariable("UGII_BASE_DIR", "Process")
}
if (-not $NXRoot) {
    $NXRoot = [Environment]::GetEnvironmentVariable("UGII_BASE_DIR", "Machine")
}
if (-not $NXRoot) { throw "UGII_BASE_DIR was not found; pass -NXRoot" }

$existing = [Environment]::GetEnvironmentVariable("UGII_USER_DIR", "User")
if ($existing) {
    $existingFull = [IO.Path]::GetFullPath($existing).TrimEnd('\')
    $wantedFull = [IO.Path]::GetFullPath($userRoot).TrimEnd('\')
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($existingFull, $wantedFull)) {
        throw "UGII_USER_DIR is already set to '$existing'. Refusing to overwrite another NX customization root."
    }
}

& $build -NXRoot $NXRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build NX remoting bridge" }

New-Item -ItemType Directory -Force -Path $startup | Out-Null
Copy-Item -LiteralPath $source -Destination $target -Force
[Environment]::SetEnvironmentVariable("UGII_USER_DIR", $userRoot, "User")

Write-Host "NX MCP auto-start installed."
Write-Host "UGII_USER_DIR=$userRoot"
Write-Host "Startup library=$target"
Write-Host "Close all NX sessions and start NX again. No Journal playback will be needed."
