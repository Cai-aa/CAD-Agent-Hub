import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def test_standalone_preflight_needs_no_native_client_or_eplan(tmp_path):
    root=Path(__file__).resolve().parents[1];workspace=tmp_path/'workspace';workspace.mkdir()
    plan=tmp_path/'plan.json';dll=tmp_path/'stub.dll'
    plan.write_text(json.dumps({'schema_version':'eplan-workstation-native-1','project_name':'Conveyor_Pusher_R1','pages':[{'number':1}]}),encoding='utf-8')
    dll.write_bytes(b'synthetic fingerprint only, never loaded')
    values={'EPLAN_WORKSTATION_ROOT':str(workspace),'EPLAN_WORKSTATION_PLAN':str(plan),'EPLAN_WORKSTATION_PLAN_SHA256':hashlib.sha256(plan.read_bytes()).hexdigest(),'EPLAN_WORKSTATION_DLL':str(dll),'EPLAN_WORKSTATION_DLL_SHA256':hashlib.sha256(dll.read_bytes()).hexdigest()}
    config=tmp_path/'environment.json';config.write_text(json.dumps(values),encoding='utf-8')
    r=subprocess.run([sys.executable,str(root/'scripts/authoring_preflight.py'),'--environment',str(config)],cwd=tmp_path,
                     env=dict(os.environ,PYTHONUTF8='1'),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    data=json.loads(r.stdout.decode('utf-8'))
    assert r.returncode==0 and data['success']
    assert not data['native_read_this_call'] and not data['native_loaded_identity_verified']
    assert data['operations']['snapshot']['configured']
    assert not data['operations']['safety_revision']['configured']


def test_template_placeholders_are_never_executable_configuration(tmp_path):
    root=Path(__file__).resolve().parents[1]
    r=subprocess.run([sys.executable,str(root/'scripts/authoring_preflight.py'),'--environment',str(root/'authoring/environment.example.json')],cwd=tmp_path,
                     env=dict(os.environ,PYTHONUTF8='1'),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    data=json.loads(r.stdout.decode('utf-8'))
    assert r.returncode==2 and not data['success'] and not data['native_read_this_call']
