[CmdletBinding()]
param(
    [string]$NXRoot = $env:UGII_BASE_DIR
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bin = Join-Path $root "bin"
$managed = Join-Path $NXRoot "NXBIN\managed"
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not $NXRoot) { throw "UGII_BASE_DIR is not set; pass -NXRoot" }
if (-not (Test-Path -LiteralPath $csc)) { throw "64-bit .NET Framework compiler not found: $csc" }
if (-not (Test-Path -LiteralPath (Join-Path $managed "NXOpen.dll"))) {
    throw "NXOpen.dll not found under $managed"
}

New-Item -ItemType Directory -Force -Path $bin | Out-Null

& $csc /nologo /target:library /platform:x64 /optimize+ `
    "/out:$bin\NXMcPRemotingServer.dll" `
    "/reference:$managed\NXOpen.dll" `
    "/reference:$managed\NXOpen.Utilities.dll" `
    "/reference:System.Runtime.Remoting.dll" `
    (Join-Path $root "NXRemotingServer.cs")
if ($LASTEXITCODE -ne 0) { throw "Failed to compile NXMcPRemotingServer.dll" }

& $csc /nologo /target:library /platform:x64 /optimize+ `
    "/out:$bin\NXMcPSimulationRuntimeV3.dll" `
    "/reference:$managed\NXOpen.dll" `
    "/reference:$managed\NXOpen.Utilities.dll" `
    "/reference:System.Web.Extensions.dll" `
    (Join-Path $root "NXSimulationRuntime.cs")
if ($LASTEXITCODE -ne 0) { throw "Failed to compile NXMcPSimulationRuntimeV3.dll" }

& $csc /nologo /target:exe /platform:x64 /optimize+ `
    "/out:$bin\NXRemoteClient.exe" `
    "/reference:$managed\NXOpen.dll" `
    "/reference:$managed\NXOpen.Utilities.dll" `
    "/reference:System.Runtime.Remoting.dll" `
    (Join-Path $root "NXRemoteClient.cs")
if ($LASTEXITCODE -ne 0) { throw "Failed to compile NXRemoteClient.exe" }

Write-Host "Built $bin\NXMcPRemotingServer.dll"
Write-Host "Built $bin\NXMcPSimulationRuntimeV3.dll"
Write-Host "Built $bin\NXRemoteClient.exe"
