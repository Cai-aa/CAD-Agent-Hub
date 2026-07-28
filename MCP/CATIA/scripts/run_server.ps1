$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$source = Join-Path $project 'src'

$candidates = @(
    @(
        $env:CATIA_MCP_PYTHON,
        (Join-Path $project '.venv\Scripts\python.exe'),
        (Get-Command python -ErrorAction SilentlyContinue).Source
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
)

if (-not $candidates) {
    throw 'No usable Python was found. Set CATIA_MCP_PYTHON or create .venv.'
}

$env:PYTHONPATH = $source
if (-not $env:CATIA_MCP_WORKSPACE) {
    $env:CATIA_MCP_WORKSPACE = Join-Path $project 'workspace'
}
if (-not $env:CATIA_MCP_ALLOWED_ROOTS) {
    $env:CATIA_MCP_ALLOWED_ROOTS = $env:CATIA_MCP_WORKSPACE
}
if (-not $env:CATIA_MCP_ENV_NAME) {
    $env:CATIA_MCP_ENV_NAME = 'CATIA_P3.V5-6R2023.B33'
}

$pythonExecutable = [string]$candidates[0]
& $pythonExecutable -m catia_mcp.server
exit $LASTEXITCODE
