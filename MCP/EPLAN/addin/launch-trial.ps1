param([Parameter(Mandatory=$true)][string]$Workspace, [string]$EplanExe = $env:EPLAN_EXE, [switch]$Visible)
$ErrorActionPreference = 'Stop'
if (-not $EplanExe -or -not (Test-Path -LiteralPath $EplanExe)) { throw 'Provide an installed EPLAN 2.9 executable' }
if (-not [IO.Path]::IsPathRooted($Workspace) -or -not (Test-Path -LiteralPath $Workspace -PathType Container)) { throw 'Workspace must be an existing absolute local directory' }
$oldTrial = $env:EPLAN_MCP_TRIAL_INSTANCE
$oldWorkspace = $env:EPLAN_MCP_WORKSPACE
try {
    $env:EPLAN_MCP_TRIAL_INSTANCE = '1'
    $env:EPLAN_MCP_WORKSPACE = (Resolve-Path -LiteralPath $Workspace).Path
    $style = if ($Visible) { 'Normal' } else { 'Hidden' }
    $process = Start-Process -FilePath $EplanExe -ArgumentList '/Variant:"Electric P8"' -WindowStyle $style -PassThru
    Write-Output "Requested dedicated trial process: PID $($process.Id). Verify discovered instance, build and trial flag before writing."
} finally {
    $env:EPLAN_MCP_TRIAL_INSTANCE = $oldTrial
    $env:EPLAN_MCP_WORKSPACE = $oldWorkspace
}
