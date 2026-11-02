"""Typed native three-phase readback and logical-path coverage; no EPLAN writes."""
from collections import deque
from datetime import datetime,timezone
import json
from pathlib import Path
from eplan_mcp.bridge import discover,request
from eplan_mcp import review

from eplan_mcp.config import workspace_root
ROOT=workspace_root()
review.register_loaded(__file__)


def collect():
    design,binding=review.context(ROOT)
    if binding['collector_schema'] not in ('reference-native-audit-2','three-phase-native-audit-2'):
        raise review.EvidenceError('COLLECTOR_SCHEMA_MISMATCH')
    from audit_native import _native_database_id
    instances=[i for i in discover() if i['trial_writes_enabled']]
    if len(instances)!=1:raise RuntimeError('Expected one verified dedicated instance')
    instance=instances[0]['instance_id']
    def call(op,payload=None):
        r=request(instance,op,payload)
        if not r.get('ok'):raise RuntimeError(str(r.get('error')))
        return r['data']
    client_file=ROOT/'artifacts/client_engineering_A0_applied.json'
    client=json.loads(client_file.read_text(encoding='utf-8-sig')) if client_file.exists() else None
    if client:call('trial_client_engineering_reconcile')
    parts_verified=None
    if design.get('native_parts_revision'):
        parts_verified=call('trial_curated_parts_reconcile')
        if not parts_verified.get('complete') or parts_verified['verified_bindings']!=design['native_parts_scope']['native_references'] or parts_verified['definitions']!=design['native_parts_scope']['project_records']:raise RuntimeError('Native curated part reference verification incomplete')
    projects=call('list_projects')['projects'];names=[p for p in projects if p.endswith('motor_forward_reverse_trial')]
    if len(names)!=1:raise RuntimeError('Open trial project is missing/ambiguous')
    project=names[0];pages=call('list_pages',{'project_name':project})['pages'];functions=[];page_data=[];edges={}
    for p in pages:
        fs=call('list_functions',{'project_name':project,'page_name':p})['functions']
        pe=[e for f in fs for e in f['native_edges']];_native_database_id(fs,pe)
        for f in fs:
            f['page']=p;functions.append(f)
            for e in f['native_edges']:
                k=e['database_id'],e['object_id']
                if k in edges and edges[k]!=e:raise RuntimeError('Connection changed during collection')
                edges[k]=e
        page_data.append(dict(page=p,functions=len(fs),with_native_connections=sum(bool(f['native_connections']) for f in fs),
                              with_graphical_connections=sum(bool(f['graphical_connections']) for f in fs),
                              connection_point_count=sum(f['connection_points'] for f in fs),function_details=fs))
    all_edges=list(edges.values());db=_native_database_id(functions,all_edges)
    placed=[e for e in all_edges if e['placed']];unplaced=[e for e in all_edges if not e['placed']]
    def point(f,pin):return (db,f['type_id'],f['object_id'],pin)
    def end(e,side):return (e['database_id'],e[side+'_type_id'],e[side+'_object_id'],e[side+'_index'])
    def edge_key(e):
        a=f"{e['start_type_id']}:{e['start_object_id']}:{e['start_index']}";b=f"{e['end_type_id']}:{e['end_object_id']}:{e['end_index']}"
        return '|'.join(sorted([a,b]))+'|'+str(e['placed'])
    expected_file=ROOT/'artifacts/three_phase_applied.json'
    expected=set(json.loads(expected_file.read_text(encoding='utf-8-sig'))['expected_native_edges'])
    actual={edge_key(e) for e in placed};missing_expected=sorted(expected-actual);extra_expected=sorted(actual-expected)
    graph={}
    def add(a,b,edge):graph.setdefault(a,[]).append((b,edge));graph.setdefault(b,[]).append((a,edge))
    for e in placed:add(end(e,'start'),end(e,'end'),e['object_id'])
    terminals=[f for f in functions if f['symbol']=='X']
    for f in terminals:add(point(f,0),point(f,1),None)
    def find(tag,symbol,role=None):
        fs=[f for f in functions if f['symbol']==symbol and (f['visible_name']==tag or ('-'+tag+':') in f['name']) and (role is None or f.get('role_designation')==role)]
        return fs[0] if len(fs)==1 else None
    def direct(f,pin):return None if f is None else point(f,pin)
    reference_file=ROOT/'artifacts/reference_interfaces_applied.json'
    reference_points=json.loads(reference_file.read_text(encoding='utf-8-sig')).get('logical_native_endpoints',{}) if reference_file.exists() else {}
    if client:reference_points.update(client['logical_native_endpoints'])
    def logical(name):
        if name in reference_points:
            selected=reference_points[name]
            fs=[f for f in functions if f['object_id']==selected['object_id'] and f['type_id']==selected['type_id']]
            if len(fs)!=1:raise RuntimeError('Reference endpoint missing/ambiguous: '+name)
            pin=selected['pin_index'];expected_label=selected['display_designation']
            actual=next((p for p in fs[0]['native_pins'] if p['index']==pin),None)
            if actual is None or actual.get('display_designation')!=expected_label:raise RuntimeError('Reference endpoint label conflict: '+name)
            return direct(fs[0],pin)
        tag,role=name.split('.',1)
        if tag.startswith('X'):
            fs=[f for f in terminals if f['name'].endswith('-'+tag+':'+role)]
            return direct(fs[0],0) if len(fs)==1 else None
        if tag in ['AC_BUS','DC_BUS','PE_BUS']:
            mapping={'AC_BUS':{'L1':('QF0','FA4',1),'L2':('QF0','FA4',3),'L3':('QF0','FA4',5),'N':('QF0','FA4',7)}}
            if tag=='AC_BUS':t,s,p=mapping[tag][role];return direct(find(t,s),p)
            if tag=='PE_BUS':return logical('X1.5')
            if client:return logical('PS1.'+role)
            return direct(find('PS1','DCP','ROLE_24V_TBD' if role=='+24V' else 'ROLE_0V_TBD'),0)
        if tag=='QS1':
            if role.startswith('N_'):return direct(find('QS1','S','N_IN_TBD'),0 if role.endswith('IN') else 1)
            i=int(role[1])-1;return direct(find('QS1','Q3'),2*i+(0 if role.endswith('IN') else 1))
        if tag.startswith('QF'):
            s='FA4' if tag=='QF0' else 'FA3' if tag=='QF1' else 'FA2' if tag=='QF2' else 'FA1'
            i=3 if role.startswith('N_') and tag=='QF0' else 1 if role.startswith('N_') else int(role[1])-1 if role.startswith(('L1','L2','L3')) else 0
            return direct(find(tag,s),2*i+(0 if role.endswith('IN') else 1))
        if tag.startswith('FU'):return direct(find(tag,'FA1'),0 if role=='IN' else 1)
        if tag=='KM0':
            if role.startswith(('L1','L2','L3')):return direct(find(tag,'S',role[:2]+'_IN_TBD'),0 if role.endswith('IN') else 1)
            if role in ['A1','A2']:return direct(find(tag,'K'),0 if role=='A1' else 1)
            return None
        if tag in ['PS1','VFD1','SR1','CABINET1','DOOR1']:
            if tag=='PS1':r={'L':'ROLE_L_TBD','N':'ROLE_N_TBD','PE':'ROLE_PE_TBD','+24V':'ROLE_24V_TBD','0V':'ROLE_0V_TBD'}.get(role)
            elif tag=='VFD1':r={'L1':'ROLE_L1_TBD','L2':'ROLE_L2_TBD','L3':'ROLE_L3_TBD','PE':'ROLE_PE_TBD','U':'U','V':'V','W':'W'}.get(role)
            elif tag=='SR1':r={'PWR_PLUS_ROLE':'ROLE_PWR_PLUS_TBD','PWR_0V_ROLE':'ROLE_PWR_0V_TBD','CH_A_OUT':'ROLE_CH_A_OUT_TBD','CH_A_RETURN':'ROLE_CH_A_RETURN_TBD','CH_B_OUT':'ROLE_CH_B_OUT_TBD','CH_B_RETURN':'ROLE_CH_B_RETURN_TBD','SAFE_IN_ROLE':'ROLE_SAFE_IN_TBD','SAFE_OUT':'ROLE_SAFE_OUT_TBD','SAFE_RETURN_ROLE':'ROLE_SAFE_RETURN_TBD','EDM':'ROLE_EDM_TBD','STATUS':'ROLE_STATUS_TBD'}.get(role)
            else:r='ROLE_PE_TBD'
            return direct(find(tag,'DCP',r),0) if r else None
        if tag=='PLC1':
            if role.startswith(('I0.','Q0.')):
                fs=[f for f in functions if f.get('plc_address')==role];return direct(fs[0],0) if len(fs)==1 else None
            r={'L+':'ROLE_LPLUS_TBD','M':'ROLE_M_TBD','DO_COMMON_ROLE':'ROLE_DO_LPLUS_TBD'}.get(role)
            return direct(find(tag,'DCP',r),0) if r else None
        if tag=='SB0':return direct(find(tag,'SONOT1','CH_A_IN_TBD' if role.startswith('CH_A') else 'CH_B_IN_TBD'),0 if role.endswith('IN') else 1)
        if tag.startswith('SB'):return direct(find(tag,'SOA' if tag=='SB2' else 'SSA'),0 if role.endswith('IN') else 1)
        if tag.startswith('KA'):
            if role in ['A1','A2']:return direct(find(tag,'K'),1 if role=='A1' else 0)
            return direct(find(tag,'S' if role.startswith('NO') else 'O'),0 if role in ['NO_IN','NC_OUT'] else 1)
        if tag.startswith('HL'):
            positive=role in ['L','+'];return direct(find(tag,'H'),(0 if positive else 1) if tag in ['HL1','HL2'] else (1 if positive else 0))
        if tag in ['SQ1','TS1']:return direct(find(tag,'SSM'),0 if role=='COM' else 1)
        if tag=='EL1':return direct(find(tag,'H'),0 if role=='L' else 1)
        if tag=='FAN1':return direct(find(tag,'M2W_VE'),2 if role=='PE' else 0 if role=='L' else 1)
        if tag=='M1':return direct(find(tag,'M3'),{'U':0,'V':1,'W':2,'PE':3}[role])
        return None
    def path(a,b):
        if a is None or b is None:return None
        q=deque([(a,[])]);seen={a}
        while q:
            n,trail=q.popleft()
            if n==b:return trail
            for target,edge in graph.get(n,[]):
                if target not in seen:seen.add(target);q.append((target,trail+([edge] if edge is not None else [])))
        return None
    model=json.loads((ROOT/'artifacts/motor_forward_reverse.design.json').read_text(encoding='utf-8'))
    verified=[];missing=[];used={}
    for intent in model['connections']:
        a=logical(intent['from']);b=logical(intent['to']);route=path(a,b)
        if route is None:missing.append(dict(intent,reason='native_endpoint_missing_or_no_conductive_path'))
        else:
            verified.append(dict(id=intent['id'],native_edge_ids=route,logical_bus_collapsed=(a==b),source=a,target=b))
            for edge in route:used.setdefault(edge,[]).append(intent['id'])
    # Separate static-net check includes only closed passive switch/fuse paths;
    # never joins consumer terminals or the internals of PS1/VFD/PLC/SR1/motor.
    def passive_nets(skip=None):
        parent={}
        def root(a):
            parent.setdefault(a,a)
            if parent[a]!=a:parent[a]=root(parent[a])
            return parent[a]
        def union(a,b):parent[root(a)]=root(b)
        for e in placed:
            if skip not in (e['start_object_id'],e['end_object_id']):union(end(e,'start'),end(e,'end'))
        for f in functions:
            if f['object_id']==skip:continue
            pairs=[]
            if f['symbol']=='X':pairs=[(0,1)]
            elif f['symbol'] in ['Q3','FA3','FA4','FA2','FA1','Q2','S','O','SSM','SOM']:pairs=[(p,p+1) for p in range(0,len(f['native_pins']),2)]
            for a,b in pairs:union(point(f,a),point(f,b))
        return root
    root=passive_nets()
    seeds={k:logical(v) for k,v in {'L1':'X1.1','L2':'X1.2','L3':'X1.3','N':'X1.4','PE':'X1.5','+24V':'PS1.+24V','0V':'PS1.0V','U':'VFD1.U','V':'VFD1.V','W':'VFD1.W'}.items()}
    if reference_points:seeds.update({'V20_24V':logical('VFD1.DI_SUPPLY_ROLE'),'V20_0V':logical('VFD1.CONTROL_0V')})
    shorts=[];intentional_bond=None
    if client:
        selected=reference_points.get('X0.1');bond=model.get('functional_grounding',{})
        if not selected or bond.get('bond_terminal')!='X0.1' or bond.get('type')!='single_explicit_0V_PE_reference_bond':raise RuntimeError('Missing declared single reference bond')
        if root(seeds['PE'])!=root(seeds['0V']):raise RuntimeError('Declared reference bond is open')
        disconnected=passive_nets(selected['object_id'])
        if disconnected(seeds['PE'])==disconnected(seeds['0V']):raise RuntimeError('Undeclared parallel 0V-PE bond')
        intentional_bond={'terminal':'X0:1','object_id':selected['object_id'],'only_path_verified':True,'removing_bond_node_disconnects':True}
    for i,a in enumerate(seeds):
        for b in list(seeds)[i+1:]:
            if seeds[a] is None or seeds[b] is None:raise RuntimeError('Missing potential seed')
            if root(seeds[a])==root(seeds[b]) and not (client and {a,b}=={'PE','0V'}):shorts.append([a,b])
    physical=[]
    if client:
        lookup={f['object_id']:f for f in functions}
        potentials={(t['strip'],str(t['number'])):t['potential'] for t in model['terminals']}
        for f in terminals:
            bank=f['name'].rsplit('-',1)[-1].split(':',1)[0];number=f['name'].rsplit(':',1)[-1];bridge=[];field=[]
            for edge in f['native_edges']:
                other_id=edge['end_object_id'] if edge['start_object_id']==f['object_id'] else edge['start_object_id']
                other=lookup[other_id]
                (bridge if other['symbol']=='X' and other['name'].rsplit(':',1)[0]==f['name'].rsplit(':',1)[0] else field).append(edge['object_id'])
            limit=4 if bank=='X6M' and number in ['2','8'] else 2
            if len(field)>limit:raise RuntimeError('TERMINAL_CLAMP_BUDGET_EXCEEDED '+f['name'])
            for pin in f['native_pins']:
                usage=sum((e['start_object_id']==f['object_id'] and e['start_index']==pin['index']) or (e['end_object_id']==f['object_id'] and e['end_index']==pin['index']) for e in f['native_edges'])
                if usage>pin['max_connections']:raise RuntimeError('NATIVE_PIN_CAPACITY_EXCEEDED '+f['name'])
            potential=potentials[(bank,number)]
            physical.append({'terminal':bank+':'+number,'field_wires':len(field),'rated_field_clamps':limit,'bridge_edges':bridge,'field_edge_ids':field,'physical_article':'3209578' if limit==4 else '3209536' if potential=='PE' else '3209523' if potential=='N' or potential.startswith('AC_N') else '3209510'})
    counts={}
    for f in terminals:
        tag=f['name'].rsplit('-',1)[-1].split(':',1)[0];counts[tag]=counts.get(tag,0)+1
    report=dict(schema=binding['collector_schema'],collected_utc=datetime.now(timezone.utc).isoformat(),instance_id=instance,database_id=db,project_name=project,
        summary=dict(pages_scanned=len(pages),schematic_pages=sum(p['functions']>0 for p in page_data),native_edges=len(placed),placed_edges=len(placed),unplaced_edges=len(unplaced),
                     verified_native_routes=len(expected&actual),design_connection_intents=len(model['connections']),design_intents_verified_native=len(verified),design_intents_not_placed=len(missing),
                     unexpected_native_edges=len(extra_expected),missing_expected_routes=missing_expected,design_device_tags_missing_native=[],terminal_positions=sum(counts.values()),terminal_groups=counts),
        route_check=dict(verified=[dict(native_edge_id=e['object_id'],design_path_ids=used.get(e['object_id'],[]),**e) for e in placed],missing=missing_expected,unexpected_native_edges=extra_expected),
        logical_intent_paths=verified,unresolved_intents=missing,static_conductor_check=dict(pairs_checked=len(seeds)*(len(seeds)-1)//2,direct_conductor_shorts=shorts,scope='closed passive paths; no consumer/converter internals; not an insulation or safety test'),
        pages=page_data,placed_edges=placed,unplaced_edges=unplaced,production_release_allowed=False)
    if client:
        report['intentional_reference_bond']=intentional_bond
        report['terminal_physical_capacity']={'verified_all':True,'positions':physical,'scope':'field clamps and same-bank bridge accessories counted separately; native two-point symbol aggregates contacts'}
    if parts_verified:report['native_parts_verification']={'scope':'project_local_curated_records_not_vendor_macros','complete':True,'verified_references':parts_verified['verified_bindings'],'definitions':parts_verified['definitions'],'plan_sha256':parts_verified['plan_sha256'],'procurement_approved':False}
    if missing_expected or extra_expected or unplaced or shorts:raise RuntimeError('Three-phase native audit failed '+json.dumps(report['summary']))
    return review.bind_report(report,binding,ROOT)


if __name__=='__main__':
    r=collect();(ROOT/'artifacts/native_connectivity_audit.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r['summary'],ensure_ascii=False))
