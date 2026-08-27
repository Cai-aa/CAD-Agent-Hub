[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$expected = [IO.Path]::GetFullPath((Join-Path $root "nx_user")).TrimEnd('\')
$current = [Environment]::GetEnvironmentVariable("UGII_USER_DIR", "User")

if (-not $current) {
    Write-Host "NX MCP auto-start is not configured in the user environment."
    exit 0
}

$currentFull = [IO.Path]::GetFullPath($current).TrimEnd('\')
if (-not [StringComparer]::OrdinalIgnoreCase.Equals($currentFull, $expected)) {
    throw "UGII_USER_DIR points to '$current', not this MCP. Nothing was changed."
}

[Environment]::SetEnvironmentVariable("UGII_USER_DIR", $null, "User")
Write-Host "Removed the NX MCP UGII_USER_DIR setting."
Write-Host "The files were preserved at $expected for recovery or inspection."
Write-Host "Restart NX for the change to take effect."
