from pathlib import Path
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import types
import pytest

@pytest.fixture
def adapter(tmp_path,monkeypatch):
    for key in list(os.environ):
        if key.startswith('EPLAN_WORKSTATION_'):monkeypatch.delenv(key)
    calls=[]
    scripted=types.ModuleType('api.actions.scripted')
    def execute(code,timeout):
        calls.append(code)
        return {'success':True,'results':{'success':True,'native_test_stub':True}}
    scripted._execute_script=execute
    for name in ['api','api.actions']:
        monkeypatch.setitem(sys.modules,name,types.ModuleType(name))
    monkeypatch.setitem(sys.modules,'api.actions.scripted',scripted)
    root=tmp_path/'EPLAN_workspace';root.mkdir()
    plan=tmp_path/'native-plan.json';dll=tmp_path/'helper.dll'
    plan.write_text(json.dumps({'schema_version':'eplan-workstation-native-1','project_name':'Conveyor_Pusher_R1','pages':[{'number':1}]}),encoding='utf-8')
    dll.write_bytes(b'only a test fingerprint, never executed')
    for k,v in {'EPLAN_WORKSTATION_ROOT':root,'EPLAN_WORKSTATION_PLAN':plan,'EPLAN_WORKSTATION_DLL':dll,'EPLAN_WORKSTATION_PLAN_SHA256':hashlib.sha256(plan.read_bytes()).hexdigest(),'EPLAN_WORKSTATION_DLL_SHA256':hashlib.sha256(dll.read_bytes()).hexdigest()}.items():monkeypatch.setenv(k,str(v))
    source=Path(__file__).resolve().parents[1]/'authoring/workstation.py'
    spec=importlib.util.spec_from_file_location('test_ws_adapter',source);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod,calls,plan,dll

def test_changed_plan_is_rejected_before_native_call(adapter):
    mod,calls,plan,_=adapter;plan.write_text('{}',encoding='utf-8')
    assert mod.prepare()['success'] is False
    assert not calls

def test_changed_dll_is_rejected_before_native_call(adapter):
    mod,calls,_,dll=adapter;dll.write_bytes(b'changed')
    assert mod.snapshot()['success'] is False
    assert not calls

def test_unplanned_page_is_rejected_before_native_call(adapter):
    mod,calls,_,_=adapter
    assert mod.apply_page(99)['success'] is False
    assert not calls

def test_wrong_project_cannot_be_selected(adapter,monkeypatch):
    mod,calls,plan,_=adapter
    data=json.loads(plan.read_text());data['project_name']='An_existing_customer_project';plan.write_text(json.dumps(data))
    monkeypatch.setenv('EPLAN_WORKSTATION_PLAN_SHA256',hashlib.sha256(plan.read_bytes()).hexdigest())
    assert mod.prepare()['success'] is False
    assert not calls

def test_fixed_adapter_keeps_result_token_and_paths_containing_plan(adapter):
    mod,calls,_,_=adapter
    assert mod.snapshot()['success']
    assert len(calls)==1
    assert '{{RESULT_PATH}}' in calls[0]
    assert '__WS_' not in calls[0]
    assert 'EPLAN_workspace' in calls[0]
    assert 'GetMethod("Execute")' in calls[0]

def test_no_caller_script_or_arbitrary_action_is_exported(adapter):
    mod,_,_,_=adapter
    assert 'execute_custom_script' not in mod.__all__
    assert mod.TOOL_PREFIX=='eplan_ws_'
    assert {'inspect_reopened_identity','bind_verified_reopened_identity','backup_project'}<=set(mod.__all__)

def test_safety_plan_without_digest_never_calls_native(adapter):
    mod,calls,_,_=adapter
    assert mod.safety_review_apply()['success'] is False
    assert not calls

def test_changed_safety_plan_never_calls_native(adapter,monkeypatch):
    mod,calls,_,_=adapter
    root=Path(__import__('os').environ['EPLAN_WORKSTATION_ROOT'])
    path=root/'workstation-safety-R2.json';path.write_text('{}')
    monkeypatch.setenv('EPLAN_WORKSTATION_SAFETY_SHA256','0'*64)
    assert mod.safety_review_apply()['success'] is False
    assert not calls

def test_notes_without_digest_never_calls_native(adapter):
    mod,calls,_,_=adapter
    assert mod.safety_review_annotations()['success'] is False
    assert not calls

def test_changed_notes_never_call_native(adapter,monkeypatch):
    mod,calls,_,_=adapter
    root=Path(__import__('os').environ['EPLAN_WORKSTATION_ROOT'])
    (root/'workstation-safety-notes.json').write_text('{}')
    monkeypatch.setenv('EPLAN_WORKSTATION_NOTES_SHA256','0'*64)
    assert mod.safety_review_annotations()['success'] is False
    assert not calls


def test_preflight_never_executes_or_promises_native_compatibility(adapter):
    mod,calls,_,_=adapter
    r=mod.preflight()
    assert r['success'] and not calls
    assert not r['native_read_this_call'] and not r['native_loaded_identity_verified']
    assert r['operations']['snapshot']['configured']
    assert not r['operations']['safety_revision']['configured']


@pytest.mark.parametrize('value',['nan','inf','0','181','-1'])
def test_invalid_timeout_is_rejected_before_native_call(adapter,monkeypatch,value):
    mod,calls,_,_=adapter;monkeypatch.setenv('EPLAN_WORKSTATION_TIMEOUT_SECONDS',value)
    assert mod.snapshot()['success'] is False and not calls


def test_configured_timeout_reaches_client_once(adapter,monkeypatch):
    mod,_,_,_=adapter;seen=[]
    monkeypatch.setenv('EPLAN_WORKSTATION_TIMEOUT_SECONDS','42')
    monkeypatch.setattr(mod,'_execute_script',lambda code,timeout:(seen.append(timeout) or {'success':True,'results':{'success':True}}))
    assert mod.snapshot()['success'] and seen==[42]


def test_missing_config_returns_diagnostic_instead_of_keyerror(adapter,monkeypatch):
    mod,calls,_,_=adapter;monkeypatch.delenv('EPLAN_WORKSTATION_ROOT')
    r=mod.snapshot();assert not r['success'] and r['native_entry_started'] is False and not calls


@pytest.mark.parametrize('page',[True,1.0,'1'])
def test_page_type_is_not_coerced_into_write_target(adapter,page):
    mod,calls,_,_=adapter;assert not mod.apply_page(page)['success'] and not calls


def test_disk_source_change_requires_new_process(adapter,tmp_path,monkeypatch):
    mod,calls,_,_=adapter;p=tmp_path/'changed.py';p.write_bytes(b'changed')
    monkeypatch.setattr(mod,'_SOURCE_PATH',p)
    r=mod.snapshot();assert not r['success'] and 'LOADED_CODE_STALE' in r['error'] and not calls


def test_duplicate_json_keys_cannot_hide_project_identity(adapter,monkeypatch):
    mod,calls,plan,_=adapter
    plan.write_text('{"schema_version":"eplan-workstation-native-1","project_name":"other","project_name":"Conveyor_Pusher_R1","pages":[{"number":1}]}')
    monkeypatch.setenv('EPLAN_WORKSTATION_PLAN_SHA256',hashlib.sha256(plan.read_bytes()).hexdigest())
    assert not mod.snapshot()['success'] and not calls


def test_invalid_mvid_never_dispatches(adapter,monkeypatch):
    mod,calls,_,_=adapter;monkeypatch.setenv('EPLAN_WORKSTATION_DLL_MVID','not-a-guid')
    assert not mod.snapshot()['success'] and not calls


def test_transport_exception_is_unknown_and_not_retried(adapter,monkeypatch):
    mod,_,_,_=adapter;seen=[]
    def timeout(*a,**kw):seen.append(1);raise TimeoutError('response deadline')
    monkeypatch.setattr(mod,'_execute_script',timeout)
    r=mod.apply_page(1)
    assert not r['success'] and r['outcome']=='unknown_after_dispatch'
    assert r['requires_readback'] and not r['automatic_retry'] and len(seen)==1


def test_malformed_native_reply_cannot_be_reported_as_success(adapter,monkeypatch):
    mod,_,_,_=adapter
    monkeypatch.setattr(mod,'_execute_script',lambda *a,**kw:{'success':True,'results':{'counts':99}})
    r=mod.apply_page(1);assert not r['success'] and r['requires_readback']


def test_actual_storage_io_error_stops_without_reconnect_loop(adapter,monkeypatch):
    mod,calls,_,_=adapter
    def fail(*a):raise OSError(5,'I/O device unavailable')
    monkeypatch.setattr(mod,'_hash',fail)
    r=mod.snapshot()
    assert r['error_code']=='STORAGE_IO_UNAVAILABLE' and r['stop_native_operations'] and not calls


@pytest.mark.skipif(os.name!='nt',reason='Exercises the actual .NET Framework loader without any EPLAN assemblies')
def test_real_clr_mvid_mismatch_blocks_helper_entry(adapter,tmp_path,monkeypatch):
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():pytest.skip('Local .NET Framework compiler unavailable')
    mod,_,_,dll=adapter
    def run(args):
        compiler_env=dict(os.environ,TEMP=str(tmp_path),TMP=str(tmp_path))
        r=subprocess.run([str(x) for x in args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW,env=compiler_env)
        assert r.returncode==0,r.stdout.decode('utf-8',errors='replace')
        return r.stdout.decode('utf-8',errors='replace').strip()
    helper=tmp_path/'helper.cs'
    helper.write_text(r'''using System;using System.IO;
namespace AiCae.Eplan {public static class WorkstationNative {
public static string Execute(string command,string root,string plan,string hash,int page,string auxiliary) {
 File.WriteAllText(Path.Combine(root,"entered-native.txt"),"entered");
 return "{\"success\":true}";
}}}''',encoding='utf-8')
    run([compiler,'/nologo','/target:library','/out:'+str(dll),helper])
    monkeypatch.setenv('EPLAN_WORKSTATION_DLL_SHA256',hashlib.sha256(dll.read_bytes()).hexdigest())
    reader=tmp_path/'mvid.cs';exe=tmp_path/'mvid.exe'
    reader.write_text('class ReadMvid {static void Main(string[] args) {System.Console.Write(System.Reflection.Assembly.LoadFrom(args[0]).ManifestModule.ModuleVersionId.ToString());}}')
    run([compiler,'/nologo','/out:'+str(exe),reader]);mvid=run([exe,dll])
    result_path=tmp_path/'result.json';script=tmp_path/'invoke.cs';invoker=tmp_path/'invoke.exe'
    def execute(code,timeout):
        code=code.replace('{{RESULT_PATH}}',str(result_path).replace('"','""'))
        code+='\nnamespace Eplan.EplApi.Scripting {public sealed class StartAttribute:System.Attribute {}}\nclass Entry {static void Main(){new WorkstationTypedCall().Run();}}'
        script.write_text(code,encoding='utf-8');run([compiler,'/nologo','/out:'+str(invoker),script]);run([invoker])
        return {'success':True,'results':json.loads(result_path.read_text(encoding='utf-8-sig'))}
    monkeypatch.setattr(mod,'_execute_script',execute)
    monkeypatch.setenv('EPLAN_WORKSTATION_DLL_MVID','11111111-1111-1111-1111-111111111111')
    root=Path(os.environ['EPLAN_WORKSTATION_ROOT'])
    denied=mod.snapshot();assert not denied['success'] and not (root/'entered-native.txt').exists()
    monkeypatch.setenv('EPLAN_WORKSTATION_DLL_MVID',mvid)
    assert mod.snapshot()['success'] and (root/'entered-native.txt').read_text()=='entered'
