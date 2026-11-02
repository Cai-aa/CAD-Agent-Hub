"""Builder contract with synthetic reference assemblies, never EPLAN SDK."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.name!='nt',reason='Windows .NET Framework builder integration')
def test_fingerprinted_build_is_cached_receipted_and_tamper_evident(tmp_path):
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not compiler.is_file() or not shell:pytest.skip('Compiler or PowerShell unavailable')
    def run(args,env=None):
        return subprocess.run([str(a) for a in args],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    valid_env=dict(os.environ,TEMP=str(tmp_path),TMP=str(tmp_path))
    references=tmp_path/'synthetic-refs';references.mkdir()
    for i,name in enumerate(['AFu','Baseu','DataModelu','HEServicesu','EServicesu']):
        src=tmp_path/f'ref{i}.cs';src.write_text(f'public class SyntheticRef{i} {{}}')
        r=run([compiler,'/nologo','/target:library','/out:'+str(references/f'Eplan.EplApi.{name}.dll'),src],valid_env)
        assert r.returncode==0,r.stdout
    isolated=tmp_path/'builder';isolated.mkdir()
    original=Path(__file__).resolve().parents[1]/'authoring/build.ps1'
    shutil.copy2(original,isolated/'build.ps1')
    (isolated/'Probe.cs').write_text('public class SyntheticBuildOnly {}')
    driver=tmp_path/'drive.ps1'
    driver.write_text('''param([string]$Builder,[string]$Refs,[string]$Out)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
& $Builder -EplanBin $Refs -OutputDir $Out | ConvertTo-Json -Depth 5 -Compress
''')
    args=[shell,'-NoProfile','-NonInteractive','-File',driver,'-Builder',isolated/'build.ps1','-Refs',references,'-Out',tmp_path/'out']
    broken_temp=dict(os.environ,TEMP=str(tmp_path/'unavailable'/'temp'),TMP=str(tmp_path/'unavailable'/'temp'))
    first=run(args,broken_temp);assert first.returncode==0,first.stdout.decode('utf-8',errors='replace')
    receipt=json.loads(first.stdout.decode('utf-8-sig').strip());binary=Path(receipt['dll']);original_bytes=binary.read_bytes()
    assert receipt['assembly_mvid'] and Path(str(binary)+'.build.json').is_file()
    second=run(args,broken_temp);assert second.returncode==0,second.stdout
    same=json.loads(second.stdout.decode('utf-8-sig').strip())
    assert same['dll_sha256']==receipt['dll_sha256'] and same['assembly_mvid']==receipt['assembly_mvid']
    binary.write_bytes(original_bytes+b'tampered')
    third=run(args,broken_temp)
    assert third.returncode!=0 and binary.read_bytes()==original_bytes+b'tampered'
