param(
    [string]$EplanBin = $env:EPLAN_BIN,
    [string]$OutputDir = (Join-Path $PSScriptRoot '..\private\authoring')
)
$ErrorActionPreference = 'Stop'
if (-not $EplanBin -and $env:EPLAN_EXE) { $EplanBin = Split-Path -Parent $env:EPLAN_EXE }
if (-not $EplanBin -or -not [System.IO.File]::Exists([System.IO.Path]::Combine($EplanBin,'Eplan.EplApi.DataModelu.dll'))) {
    throw 'Provide the installed, compatible EPLAN 2.9 API directory through EplanBin or EPLAN_EXE.'
}
$sources = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' -File | Sort-Object Name)
$bundle = New-Object System.IO.MemoryStream
foreach ($file in $sources) {
    $nameBytes = [System.Text.Encoding]::UTF8.GetBytes($file.Name)
    $bundle.Write($nameBytes,0,$nameBytes.Length)
    $bundle.WriteByte(0)
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $bundle.Write($bytes,0,$bytes.Length)
}
$sha = [System.Security.Cryptography.SHA256]::Create()
try { $hash = ([BitConverter]::ToString($sha.ComputeHash($bundle.ToArray()))).Replace('-','').ToLowerInvariant() }
finally { $sha.Dispose(); $bundle.Dispose() }
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Local .NET Framework compiler is missing.' }
$referenceFiles = @('Eplan.EplApi.AFu.dll','Eplan.EplApi.Baseu.dll','Eplan.EplApi.DataModelu.dll','Eplan.EplApi.HEServicesu.dll','Eplan.EplApi.EServicesu.dll')
$referenceHashes = [ordered]@{}
foreach ($name in $referenceFiles) {
    $referenceHashes[$name] = (Get-FileHash -LiteralPath (Join-Path $EplanBin $name) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$compilerHash = (Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant()
$identityText = $hash + '|' + $compilerHash + '|' + ($referenceHashes | ConvertTo-Json -Compress)
$sha = [System.Security.Cryptography.SHA256]::Create()
try { $buildHash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($identityText)))).Replace('-','').ToLowerInvariant() }
finally { $sha.Dispose() }
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if ($OutputDir.StartsWith('\\')) { throw 'Use a local output directory.' }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$filename = 'AiCae.Eplan.Workstation_' + $buildHash.Substring(0,16) + '.dll'
$output = Join-Path $OutputDir $filename
$receiptPath = $output + '.build.json'
$previous = $null
if ((Test-Path -LiteralPath $receiptPath) -and -not (Test-Path -LiteralPath $output)) { throw 'Build receipt exists but its DLL is missing; inspect or choose a fresh OutputDir.' }
if (Test-Path -LiteralPath $output) {
    if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'Existing DLL has no build receipt; choose a fresh OutputDir instead of trusting or overwriting it.' }
    $previous = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    if ($previous.build_sha256 -ne $buildHash -or $previous.dll_sha256 -ne (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw 'Existing compiler output or receipt changed; no overwrite.'
    }
} else {
    $staging = Join-Path $OutputDir ('compiler-temp\build-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    $stagedDll = Join-Path $staging $filename
    $arguments = @('/nologo','/target:library','/platform:x64','/codepage:65001','/optimize+',('/out:'+$stagedDll),'/reference:System.Windows.Forms.dll','/reference:System.Web.Extensions.dll')
    foreach ($name in $referenceFiles) { $arguments += '/reference:' + (Join-Path $EplanBin $name) }
    $arguments += @($sources | ForEach-Object { $_.FullName })
    # Other CAE launchers can leave TEMP/TMP pointing at an unavailable volume.
    # Use a task-local compiler directory and restore only this process's values.
    $oldTemp = $env:TEMP
    $oldTmp = $env:TMP
    try {
        $env:TEMP = $staging
        $env:TMP = $staging
        & $compiler @arguments
        if ($LASTEXITCODE -ne 0) { throw 'Typed authoring helper compilation failed.' }
    } finally { $env:TEMP = $oldTemp; $env:TMP = $oldTmp }
    if (-not (Test-Path -LiteralPath $stagedDll) -or (Get-Item -LiteralPath $stagedDll).Length -eq 0) { throw 'Compiler did not produce a nonempty DLL.' }
    if (Test-Path -LiteralPath $output) { throw 'Output appeared during compilation; inspect before continuing.' }
    Move-Item -LiteralPath $stagedDll -Destination $output
}
$assembly = [System.Reflection.Assembly]::LoadFile((Resolve-Path -LiteralPath $output).Path)
$receipt = [pscustomobject]@{
    dll=(Resolve-Path -LiteralPath $output).Path
    source_sha256=$hash
    source_bundle_sha256=$hash
    build_sha256=$buildHash
    compiler_sha256=$compilerHash
    reference_sha256=$referenceHashes
    dll_sha256=(Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
    assembly_mvid=$assembly.ManifestModule.ModuleVersionId.ToString()
    native_build='2.9.4.14642'
}
if ((Test-Path -LiteralPath $receiptPath) -and $previous.assembly_mvid -ne $receipt.assembly_mvid) { throw 'Existing DLL MVID differs from its receipt.' }
if (-not (Test-Path -LiteralPath $receiptPath)) {
    [System.IO.File]::WriteAllText($receiptPath,($receipt | ConvertTo-Json -Depth 5),[System.Text.UTF8Encoding]::new($false))
}
$receipt
