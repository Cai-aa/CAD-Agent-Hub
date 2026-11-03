param([string]$EplanBin = $env:EPLAN_BIN, [string]$OutputDir = (Join-Path $PSScriptRoot '..\private\addin'))
$ErrorActionPreference = 'Stop'
if (-not $EplanBin -and $env:EPLAN_EXE) { $EplanBin = Split-Path -Parent $env:EPLAN_EXE }
if (-not $EplanBin -or -not (Test-Path -LiteralPath (Join-Path $EplanBin 'Eplan.EplApi.DataModelu.dll'))) {
    throw 'Set EPLAN_BIN or EPLAN_EXE to your installed EPLAN 2.9 API directory.'
}
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '64-bit .NET Framework compiler is unavailable' }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$output = Join-Path $OutputDir 'Codex.EplAddin.Bridge.dll'
$references = @('Eplan.EplApi.AFu.dll','Eplan.EplApi.Baseu.dll','Eplan.EplApi.DataModelu.dll','Eplan.EplApi.HEServicesu.dll','Eplan.EplApi.EServicesu.dll')
$arguments = @('/nologo','/target:library','/platform:x64','/optimize+','/codepage:65001',"/out:$output",'/reference:System.Windows.Forms.dll','/reference:System.Web.Extensions.dll')
foreach ($name in $references) { $arguments += '/reference:' + (Join-Path $EplanBin $name) }
$arguments += @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' | Sort-Object Name | ForEach-Object FullName)
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw "C# compile failed: $LASTEXITCODE" }
Get-Item -LiteralPath $output | Select-Object FullName,Length,LastWriteTime
