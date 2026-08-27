[CmdletBinding()]
param(
    [string]$ServerName = "siemens-nx",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$requirements = Join-Path $root "requirements.txt"
$server = Join-Path $root "server.py"
$bridgeBuild = Join-Path $root "dotnet_bridge\build_bridge.ps1"

if (-not (Test-Path -LiteralPath $venvPython)) {
    if (-not $Python) {
        $resolved = Get-Command python -ErrorAction Stop
        $Python = $resolved.Source
    }
    & $Python -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv" }
}

& $venvPython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependencies" }

& $bridgeBuild
if ($LASTEXITCODE -ne 0) { throw "Failed to build the non-blocking NX remoting bridge" }

$codex = (Get-Command codex.cmd -ErrorAction Stop).Source
$registeredNames = @(& $codex mcp list 2>$null | ForEach-Object {
    if ($_ -match '^([^\s]+)\s+') { $matches[1] }
})
if ($registeredNames -contains $ServerName) {
    throw "MCP server '$ServerName' already exists. Remove or rename it explicitly before reinstalling."
}

& $codex mcp add $ServerName `
    --env NX_MCP_TRANSPORT=remoting `
    --env NX_MCP_HOST=127.0.0.1 `
    --env NX_MCP_REMOTING_PORT=48161 `
    --env NX_MCP_TIMEOUT=120 `
    --env NX_MCP_ALLOW_EXECUTE=1 `
    -- $venvPython $server
if ($LASTEXITCODE -ne 0) { throw "codex mcp add failed" }

Write-Host "Registered MCP server '$ServerName'."
Write-Host "Next: in NX, play $root\start_bridge.py once and open a work part."
Write-Host "Then run: $venvPython $root\diagnose.py"
