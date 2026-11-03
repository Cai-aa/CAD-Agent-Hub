"""Fixed project-local catalog plan validation; never opens EPLAN or a parts DB."""
from pathlib import Path
import hashlib,json

EXPECTED_PLAN_SHA256='75182f621b6a3c223c3b96bb36e55cdec0c4ad665aed9e161162d552cfc1b947'
EXPECTED_DOC_SHA256='d0f0a4a7ecd752908ced88961c169a1a8648a9f9fd07e00e069a217f56b05ce5'
PLAN_NAME='curated_parts_A1.plan.json'

def validate_plan(plan):
    if plan.get('schema')!='project-curated-parts-1':raise ValueError('CURATED_SCHEMA_UNSUPPORTED')
    if plan.get('construction_release_allowed') is not False or plan.get('system_database_write') is not False:raise ValueError('CURATED_SCOPE_INVALID')
    definitions=plan['definitions'];bindings=plan['bindings']
    keys=[d['part_key'] for d in definitions]
    if not keys or len(keys)!=len(set(keys)) or any(not k.startswith('CODEX.CURATED.A1.') for k in keys):raise ValueError('CURATED_PART_KEY_INVALID')
    for d in definitions:
        if not d.get('manufacturer') or not d.get('order_number') or not d.get('source_ids') or d.get('vendor_macro') is not False:raise ValueError('CURATED_PROVENANCE_MISSING')
        for name,value in d.get('dimensions_mm',{}).items():
            if name not in ['width','height','depth'] or isinstance(value,bool) or not isinstance(value,(int,float)) or not 0<value<3000:raise ValueError('CURATED_DIMENSION_INVALID')
    links=[(b['object_id'],b['part_key']) for b in bindings]
    if not bindings or len(links)!=len(set(links)) or any(b['part_key'] not in keys or type(b['count']) is not int or b['count']!=1 for b in bindings):raise ValueError('CURATED_BINDING_INVALID')
    if len(plan['expected_native_edges'])!=161:raise ValueError('CURATED_NATIVE_BASELINE_INVALID')
    if any(b['tag'] in ['KM0','VFD1','M1','QF0','QF1','QS1'] for b in bindings):raise ValueError('CURATED_UNRESOLVED_POWER_PART')
    return True

def load_pinned(root):
    path=Path(root)/'artifacts'/PLAN_NAME;data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED_PLAN_SHA256:raise ValueError('CURATED_PLAN_HASH_MISMATCH')
    plan=json.loads(data.decode('utf-8-sig'));validate_plan(plan);return plan

def load_document_pinned(root):
    data=(Path(root)/'artifacts/parts_caption_A1.plan.json').read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED_DOC_SHA256:raise ValueError('PARTS_CAPTION_PLAN_HASH_MISMATCH')
    plan=json.loads(data.decode('utf-8-sig'))
    if plan['schema']!='parts-caption-plan-1' or plan['construction_release_allowed'] is not False or len(plan['captions'])>20 or any(p['page'] not in ['/12','/13'] for p in plan['captions']):raise ValueError('PARTS_CAPTION_SCOPE_INVALID')
    return plan
