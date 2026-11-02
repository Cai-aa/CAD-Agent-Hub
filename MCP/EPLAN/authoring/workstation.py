"""Typed, plan-bound native EPLAN workstation operations for Canary MCP."""
import hashlib
import json
import math
import os
from pathlib import Path
import uuid
try:
    from api.actions.scripted import _execute_script
except ImportError:
    _execute_script = None  # Offline configuration inspection needs no Canary.

_SOURCE_PATH = Path(__file__).resolve()
_LOADED_SOURCE_SHA256 = hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest()
_COMMANDS = frozenset({'prepare','catalog','snapshot','apply_page','export','check',
                      'repair_sources','normalize','format','polish','inspect_reopen',
                      'bind_reopen','backup','safety_revision','safety_notes'})
_READS = frozenset({'catalog','snapshot','inspect_reopen'})
_AUX = {'format':('FORMAT','workstation-layout.json'),
        'polish':('FORMAT','workstation-layout.json'),
        'inspect_reopen':('REBIND','workstation-identity-baseline.json'),
        'bind_reopen':('REBIND','workstation-identity-baseline.json'),
        'safety_revision':('SAFETY','workstation-safety-R2.json'),
        'safety_notes':('NOTES','workstation-safety-notes.json')}

TOOL_PREFIX='eplan_ws_'
__all__=['preflight','prepare','catalog','snapshot','apply_page','export_pdf','check_project','repair_star_sources','normalize_connections','format_drawing','polish_annotations','inspect_reopened_identity','bind_verified_reopened_identity','backup_project','safety_review_apply','safety_review_annotations']


def _unique_json(pairs):
    data={}
    for k,v in pairs:
        if k in data:raise ValueError('Duplicate JSON key: '+k)
        data[k]=v
    return data


def _hash(path):
    with path.open('rb') as f:
        h=hashlib.sha256()
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def _configured(command=None):
    config={}
    for name in ['ROOT','PLAN','DLL']:
        key='EPLAN_WORKSTATION_'+name;value=os.environ.get(key,'')
        if not value or '<' in value or '>' in value or value.startswith(('\\\\','//')):
            raise ValueError('Configure an explicit absolute local '+key)
        p=Path(value).expanduser()
        if not p.is_absolute():raise ValueError('Absolute local path required: '+key)
        if os.name=='nt' and p.drive and not Path(p.anchor).is_dir():
            raise OSError(5,'Configured local volume is unavailable',p.anchor)
        config[name]=p.resolve()
    if config['ROOT'].exists() and not config['ROOT'].is_dir():raise ValueError('Workspace root is not a directory')
    if command is not None and command!='prepare' and not config['ROOT'].is_dir():raise ValueError('Owned workspace is unavailable; inspect storage/configuration')
    for name in ['PLAN','DLL']:
        key='EPLAN_WORKSTATION_'+name+'_SHA256';value=os.environ.get(key,'').lower()
        if len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Configure a SHA256 hex digest: '+key)
        if _hash(config[name])!=value:raise ValueError(name+' fingerprint mismatch')
        config[name+'_SHA256']=value
    obj=json.loads(config['PLAN'].read_text(encoding='utf-8-sig'),object_pairs_hook=_unique_json)
    if not isinstance(obj,dict) or obj.get('schema_version')!='eplan-workstation-native-1' or obj.get('project_name')!='Conveyor_Pusher_R1':
        raise ValueError('Unsupported dedicated project plan')
    pages=obj.get('pages')
    if not isinstance(pages,list) or not 1<=len(pages)<=500 or any(not isinstance(p,dict) or type(p.get('number')) is not int or not 1<=p['number']<=500 for p in pages):
        raise ValueError('Invalid planned page numbers')
    if len({p['number'] for p in pages})!=len(pages):raise ValueError('Duplicate planned page number')
    config['PAGES']={p['number'] for p in pages}
    timeout=float(os.environ.get('EPLAN_WORKSTATION_TIMEOUT_SECONDS','75'))
    if not math.isfinite(timeout) or not 1<=timeout<=180:raise ValueError('Timeout must be finite and between 1 and 180 seconds')
    config['TIMEOUT']=timeout
    mvid=os.environ.get('EPLAN_WORKSTATION_DLL_MVID','')
    config['MVID']=str(uuid.UUID(mvid)) if mvid else ''
    if config['MVID']=='00000000-0000-0000-0000-000000000000':raise ValueError('MVID must be a nonzero GUID')
    if _hash(_SOURCE_PATH)!=_LOADED_SOURCE_SHA256:raise ValueError('LOADED_CODE_STALE_RESTART_MCP')
    config['AUX_HASH']=os.environ.get('EPLAN_WORKSTATION_FORMAT_SHA256','')
    if command in _AUX:
        name,file=_AUX[command];digest=os.environ.get('EPLAN_WORKSTATION_'+name+'_SHA256','').lower()
        if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('Missing reviewed '+name+' fingerprint')
        if _hash(config['ROOT']/file)!=digest:raise ValueError(name+' fingerprint mismatch')
        config['AUX_HASH']=digest
    return config


def _precheck_failure(exc):
    storage_error=isinstance(exc,OSError) and (getattr(exc,'winerror',None) in {21,1117,1167,1005,1392} or getattr(exc,'errno',None)==5)
    return {'success':False,'error':str(exc),'error_code':'STORAGE_IO_UNAVAILABLE' if storage_error else 'AUTHORING_PRECHECK_FAILED',
            'native_entry_started':False,'partial_write_possible':False,'automatic_retry':False,
            'stop_native_operations':storage_error,'next_step':'Inspect the named volume; no disk repair or reconnect loop.' if storage_error else 'Correct configuration or start a fresh MCP process, then inspect before invoking.'}


def preflight() -> dict:
    """Inspect local plan/DLL fingerprints, source freshness and operation prerequisites without connecting to or starting EPLAN. Reports optional MVID guard and auxiliary-plan failures separately; does not prove loaded native compatibility or licensing."""
    try:
        c=_configured()
    except (OSError,ValueError,TypeError,UnicodeError) as exc:return _precheck_failure(exc)
    operations={}
    for cmd in sorted(_COMMANDS):
        try:_configured(cmd);operations[cmd]={'configured':True}
        except (OSError,ValueError,TypeError,UnicodeError) as exc:operations[cmd]={'configured':False,'reason':str(exc)}
    return {'success':True,'scope':'offline_configuration_only','native_read_this_call':False,
            'source_sha256':_LOADED_SOURCE_SHA256,'plan_sha256':c['PLAN_SHA256'],'dll_sha256':c['DLL_SHA256'],
            'client_dependency_available':_execute_script is not None,'timeout_seconds':c['TIMEOUT'],
            'timeout_scope':'upstream_result_file_wait; remote execution and diagnostic calls have independent deadlines',
            'mvid_guard_enabled':bool(c['MVID']),'expected_mvid':c['MVID'] or None,
            'native_loaded_identity_verified':False,'operations':operations,
            'construction_release':False,'commissioning_release':False}

def _fixed(command,page=0):
    if command not in _COMMANDS:return {'success':False,'error':'Command not allowed','native_entry_started':False}
    try:c=_configured(command)
    except (OSError,ValueError,TypeError,UnicodeError) as exc:return _precheck_failure(exc)
    root,plan,dll,expected=c['ROOT'],c['PLAN'],c['DLL'],c['PLAN_SHA256']
    if command=='apply_page' and (type(page) is not int or page not in c['PAGES']):
        return {'success':False,'error':'Page is not in the immutable plan','native_entry_started':False}
    if _execute_script is None:return {'success':False,'error':'Canary scripting client is unavailable; offline preflight remains usable','native_entry_started':False}
    def cs(s):return '@"'+str(s).replace('"','""')+'"'
    # This constant adapter invokes only the compiled, typed allowlist. It does
    # not accept a caller script, action name, path or replacement C# source.
    code='''using System;
using System.IO;
using System.Reflection;
using Eplan.EplApi.Scripting;
public class WorkstationTypedCall {
 [Start] public void Run() {
  try {
   Assembly a=Assembly.LoadFrom(__WS_DLL__);
   if(!String.Equals(Path.GetFullPath(a.Location),Path.GetFullPath(__WS_DLL__),StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("Loaded helper assembly path differs from the reviewed DLL");
   string wantedMvid=__WS_MVID__;
   if(wantedMvid.Length>0 && a.ManifestModule.ModuleVersionId!=new Guid(wantedMvid))throw new InvalidOperationException("Loaded helper MVID differs; do not reuse a stale assembly");
   string result=(string)a.GetType("AiCae.Eplan.WorkstationNative").GetMethod("Execute").Invoke(null,new object[]{__WS_COMMAND__,__WS_ROOT__,__WS_PLAN__,__WS_HASH__,__WS_PAGE__,__WS_FORMAT_HASH__});
   File.WriteAllText(@"{{RESULT_PATH}}",result);
  } catch(Exception ex) {
   string m=ex.ToString().Replace("\\\\","\\\\\\\\").Replace("\\\"","\\\\\\\"").Replace("\\r","\\\\r").Replace("\\n","\\\\n");
   File.WriteAllText(@"{{RESULT_PATH}}","{\\\"success\\\":false,\\\"error\\\":\\\""+m+"\\\"}");
  }
 }
}'''
    for key,value in [('DLL',cs(dll)),('COMMAND',cs(command)),('ROOT',cs(root)),('PLAN',cs(plan)),('HASH',cs(expected)),('PAGE',str(int(page))),('FORMAT_HASH',cs(c['AUX_HASH'])),('MVID',cs(c['MVID']))]:
        code=code.replace('__WS_'+key+'__',value)
    try:result=_execute_script(code,timeout=c['TIMEOUT'])
    except Exception as exc:
        return {'success':False,'error':str(exc),'outcome':'unknown_after_dispatch','automatic_retry':False,'requires_readback':command not in _READS}
    if not isinstance(result,dict) or not result.get('success'):
        return {'success':False,'error':'Native transport did not return success','transport_result':result,
                'outcome':'unknown_after_dispatch','automatic_retry':False,'requires_readback':command not in _READS}
    data=result.get('results',{})
    if not isinstance(data,dict) or type(data.get('success')) is not bool:
        return {'success':False,'error':'Malformed typed native reply','outcome':'unknown_after_dispatch','automatic_retry':False,'requires_readback':command not in _READS}
    data['plan_sha256']=expected
    data['dll_sha256']=c['DLL_SHA256']
    data['automatic_retry']=False
    if not data['success']:data['requires_readback']=bool(data.get('partial_write_possible',command not in _READS))
    return data

def prepare() -> dict:
    """Create only a fresh dedicated workstation project from the pinned template; never overwrite existing files. Read back PID, build, project database and page identities."""
    return _fixed('prepare')

def catalog() -> dict:
    """Read selected installed native symbols and pin geometry in the owned workstation. No drawing edits."""
    return _fixed('catalog')

def snapshot() -> dict:
    """Read the owned workstation's current native pages, functions and connections; never reads another project."""
    return _fixed('snapshot')

def apply_page(page_number: int) -> dict:
    """Apply one reviewed immutable page plan to the owned workstation, enforcing target and plan identities; no automatic retry after partial failure."""
    return _fixed('apply_page',page_number)

def export_pdf() -> dict:
    """Export only the owned workstation's native pages to its configured artifact directory and verify the output."""
    return _fixed('export')

def check_project() -> dict:
    """Run native checks on the owned workstation; reports messages without approving machine safety or construction."""
    return _fixed('check')

def repair_star_sources() -> dict:
    """Repair only plan-bound owned BPIN source flags after validating all native identities; preserves geometry and regenerates connections for full readback."""
    return _fixed('repair_sources')

def normalize_connections() -> dict:
    """Select star roots from actual native pin capacity without changing limits; synchronize the two PLC box descriptions and return the effective typed edge plan."""
    return _fixed('normalize')

def format_drawing() -> dict:
    """Apply the separately hash-bound typography/placement revision only after validating owned objects and baseline state. Preserve every electrical net; create continuous native wires on aligned power paths and add 2D concept pages."""
    return _fixed('format')

def polish_annotations() -> dict:
    """Resolve the verified box-title/power-pin text overlaps and mark the graph-readback status; changes only owned text and verifies the native edge set is unchanged."""
    return _fixed('polish')

def inspect_reopened_identity() -> dict:
    """Read-only: compare every stable object, page, PLC pin/address and typed connection to the hash-bound last native baseline after an EPLAN restart. Does not relax ownership or update metadata."""
    return _fixed('inspect_reopen')

def bind_verified_reopened_identity() -> dict:
    """Rebind session-local database IDs only after full live equality with the signed native baseline; changes only bridge metadata, not the EPLAN drawing."""
    return _fixed('bind_reopen')

def backup_project() -> dict:
    """Make a non-overwriting native ZW1 BACKUP of only the verified owned workstation, under its local backups directory. Does not expose archive/source-out methods or arbitrary paths."""
    return _fixed('backup')


def safety_review_apply() -> dict:
    """Apply the exact reviewed R1-to-R2 safety delta to the owned workstation once, checking the full preimage and native endpoint graph. Does not certify stopping time, pneumatic safety, PL/SIL or construction readiness. Never automatically retry."""
    return _fixed('safety_revision')


def safety_review_annotations() -> dict:
    """Apply a separate SHA256-bound R2 annotation/contact-image plan only after verifying the exact text preimage and unchanged full native graph. No wiring or device-position changes; no automatic retry."""
    return _fixed('safety_notes')
