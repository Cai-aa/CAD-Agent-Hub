param([Parameter(Mandatory=$true)][string]$DllPath, [string]$EplanExe = $env:EPLAN_EXE)
$ErrorActionPreference = 'Stop'
if (-not $EplanExe -or -not (Test-Path -LiteralPath $EplanExe)) { throw 'Provide your installed EPLAN 2.9 executable' }
if (-not (Test-Path -LiteralPath $DllPath -PathType Leaf)) { throw 'Compile the Add-in and provide its absolute DLL path' }
if (Get-Process -Name EPLAN -ErrorAction SilentlyContinue) { throw 'Close the intended EPLAN instances normally before registering a replacement; do not terminate user processes' }
$resolvedDll = (Resolve-Path -LiteralPath $DllPath).Path
$arguments = '/Variant:"Electric P8" /NoSplash /Frame:0 /Auto /Quiet EplApiModuleAction /register:"' + $resolvedDll + '"'
$process = Start-Process -FilePath $EplanExe -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "EPLAN registration returned $($process.ExitCode)" }
Write-Output 'Registration action completed. Verify the loaded native instance and build before use.'
