using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.MasterData;
using Eplan.EplApi.DataModel.EObjects;
using Eplan.EplApi.HEServices;
using DrawingText=Eplan.EplApi.DataModel.Graphics.Text;
using DrawingRectangle=Eplan.EplApi.DataModel.Graphics.Rectangle;
namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private const string ReferencePlanHash="052732176ed6cfa0a22f03279ef423b7dda428980731f8db918c286c142ff423";
        private static string ReferenceRoot { get { return RuntimePath(@""); } }
        private sealed class RefEnd {public Function F;public int Pin;public RefEnd(Function f,int pin){F=f;Pin=pin;}}
        private static void RefLabel(Function f,string a,string b=null)
        {PhaseRoleLabel(f,a,b);ChineseHideLongFunctionText(f);}
        private static void RefMove(Function f,Page page,double x,double y)
        {
            var ips=new List<InterruptionPoint>();foreach(PinBase pin in f.GraphicalConnectionPoints)
                if(f.Connections.Length>0){try{var ip=PhaseAttached(f,pin.Index);if(!ips.Contains(ip))ips.Add(ip);}catch(InvalidOperationException){}}
            double dx=x-f.Location.X,dy=y-f.Location.Y;f.Page=page;f.Location=new PointD(x,y);
            foreach(var ip in ips){var location=ip.Location;ip.Page=page;ip.Location=new PointD(location.X+dx,location.Y+dy);}
        }
        private static void RefWire(Project p,RefEnd a,RefEnd b,string name,SortedSet<string> expected)
        {AttachTrialInterruption(p,a.F,a.Pin,name,16,true,100);AttachTrialInterruption(p,b.F,b.Pin,name,16,false,101);expected.Add(PhaseEdgeKey(a.F,a.Pin,b.F,b.Pin));}
        private static void RefFork(Project p,RefEnd source,RefEnd a,RefEnd b,string name,SortedSet<string> expected)
        {AttachTrialInterruption(p,source.F,source.Pin,name,16,true,100);AttachTrialInterruption(p,a.F,a.Pin,name,16,false,101);AttachTrialInterruption(p,b.F,b.Pin,name,16,false,102);expected.Add(PhaseEdgeKey(source.F,source.Pin,a.F,a.Pin));expected.Add(PhaseEdgeKey(source.F,source.Pin,b.F,b.Pin));}
        private static void RefTransfer(Project p,Function old,Function next,int pin,SortedSet<string> expected)
        {
            var ip=PhaseAttached(old,0);
            foreach(Connection e in old.Connections)
            {
                var other=(e.StartSymbolReference==old?e.EndSymbolReference:e.StartSymbolReference) as Function;
                int index=e.StartSymbolReference==old?e.EndIndex:e.StartIndex;
                if(other==null || !expected.Remove(PhaseEdgeKey(old,0,other,index)))throw new InvalidOperationException("Reference transfer conflict");
                expected.Add(PhaseEdgeKey(next,pin,other,index));
            }
            ip.Page=next.Page;ip=RefOrientIP(p,ip,next,pin);PhaseMoveIP(ip,next,pin);old.Remove();
        }
        private static InterruptionPoint RefOrientIP(Project p,InterruptionPoint ip,Function f,int pin)
        {PinBase selected=null;foreach(PinBase candidate in f.GraphicalConnectionPoints)if(candidate.Index==pin)selected=candidate;
            string direction=selected.Direction.ToString();int variant=direction=="Up"?1:direction=="Down"?3:direction=="Left"?2:0;
            if(ip.SymbolVariant.VariantNr==variant)return ip;
            var page=ip.Page;var location=ip.Location;string name=ip.Name,visible=ip.VisibleName;bool source=ip.IsStarSource;string sort=ip.Properties.INTERRUPTIONPOINT_SORT_CODE.ToString();
            var v=new SymbolVariant();v.Initialize(new Symbol(new SymbolLibrary(p,"SPECIAL"),"BPIN"),variant);
            var replacement=new InterruptionPoint();replacement.Create(page,v);replacement.Name=name;replacement.VisibleName=visible;replacement.Location=location;replacement.IsStarSource=source;
            int code;if(Int32.TryParse(sort,out code))replacement.Properties.INTERRUPTIONPOINT_SORT_CODE=code;ip.Remove();return replacement;}
        private static Function RefFind(Project p,string tag,string symbol,string label)
        {Function result=null;foreach(Page page in p.Pages)foreach(Function f in page.Functions)
            if(f.SymbolVariant!=null && f.SymbolVariant.SymbolName==symbol && (f.VisibleName==tag || f.Name.IndexOf("-"+tag+":",StringComparison.Ordinal)>=0) && f.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString()==label)
            {if(result!=null)throw new InvalidOperationException("Ambiguous reference label "+tag+":"+label);result=f;}
            if(result==null)throw new InvalidOperationException("Missing reference label "+tag+":"+label);return result;}
        private static Dictionary<string,RefEnd> RefReadEndpoints(Project p)
        {
            var map=new Dictionary<string,RefEnd>();string[] srRoles={"PWR_PLUS_ROLE","PWR_0V_ROLE","CH_A_OUT","CH_A_RETURN","CH_B_OUT","CH_B_RETURN","EDM_SEND","EDM_RETURN","TEST3","INPUT3"},srLabels={"A1","A2","T1","IN1","T2","IN2","T4","INF/S","T3","IN3"};
            for(int i=0;i<srRoles.Length;i++)map["SR1."+srRoles[i]]=new RefEnd(RefFind(p,"SR1","DCP",srLabels[i]),0);
            var safe=RefFind(p,"SR1","S","13");map["SR1.SAFE_IN_ROLE"]=new RefEnd(safe,0);map["SR1.SAFE_OUT"]=new RefEnd(safe,1);
            var status=RefFind(p,"SR1","S","23");map["SR1.STATUS_COMMON_ROLE"]=new RefEnd(status,0);map["SR1.STATUS"]=new RefEnd(status,1);
            var feedback=RefFind(p,"KM0","O","22");map["KM0.EDM_IN"]=new RefEnd(feedback,1);map["KM0.EDM_OUT"]=new RefEnd(feedback,0);
            var reset=RefFind(p,"SB5","SSA","NO_IN_TBD");map["SB5.NO_IN"]=new RefEnd(reset,0);map["SB5.NO_OUT"]=new RefEnd(reset,1);
            var resistor=RefFind(p,"R1","R","1");map["R1.IN"]=new RefEnd(resistor,0);map["R1.OUT"]=new RefEnd(resistor,1);
            string[] roles={"DI_SUPPLY_ROLE","CONTROL_0V","DI_REFERENCE_ROLE","DI1","DI2","RESET","READY_COMMON_ROLE","READY"},labels={"13","14","12","8","9","10","15+","16-"};
            for(int i=0;i<roles.Length;i++)map["VFD1."+roles[i]]=new RefEnd(RefFind(p,"VFD1","DCP",labels[i]),0);
            var fault=RefFind(p,"VFD1","S","19");map["VFD1.FAULT_COMMON_ROLE"]=new RefEnd(fault,0);map["VFD1.FAULT"]=new RefEnd(fault,1);return map;
        }
        private Dictionary<string,object> ReconcileTrialReferenceInterfaces(ProjectManager pm,Project[] projects)
        {
            string planFile=Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces.plan.json"),partial=Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces_partial.json"),record=Path.Combine(ReferenceRoot,@"artifacts\three_phase_applied.json"),marker=Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces_applied.json");
            if(FileSha256(planFile)!=ReferencePlanHash)return Error("REFERENCE_PLAN_HASH_MISMATCH","Pinned plan changed");
            var serializer=new JavaScriptSerializer();Project trial=null;string path=Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk");foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;if(trial==null)trial=pm.OpenProject(path);
            if(File.Exists(marker))return CompleteTrialReferenceInterfaces(pm,new[]{trial});
            if(!File.Exists(partial))return Error("REFERENCE_PARTIAL_MISSING","No captured partial state");
            var state=(Dictionary<string,object>)serializer.DeserializeObject(File.ReadAllText(partial,Encoding.UTF8));
            if(Convert.ToString(state["stage"])!="generate and verify full native edge set")return Error("REFERENCE_RECONCILE_STAGE_CONFLICT","Only captured orientation mismatch can be repaired");
            var expected=new SortedSet<string>();var checkpoint=new SortedSet<string>();foreach(object e in (object[])state["expected"])expected.Add(Convert.ToString(e));foreach(object e in (object[])state["actual"])checkpoint.Add(Convert.ToString(e));
            var current=ChineseEdges(trial);if(expected.Count!=151 || checkpoint.Count!=149 || (!checkpoint.SetEquals(current) && !expected.SetEquals(current)))return Error("REFERENCE_RECONCILE_CONFLICT","Preserve changed partial circuit");
            var contact=RefFind(trial,"SR1","S","13");Page page=FindTrialPage(trial,"/19");var ips=new InterruptionPoint[2];
            for(int pin=0;pin<2;pin++)foreach(Placement placement in page.AllPlacements)
            {var ip=placement as InterruptionPoint;if(ip!=null && Math.Abs(ip.Location.X-contact.Location.X)<0.001 && Math.Abs(ip.Location.Y-(contact.Location.Y+(pin==0?24:-24)))<0.001){if(ips[pin]!=null)return Error("REFERENCE_RECONCILE_IP_CONFLICT","Ambiguous orientation target");ips[pin]=ip;}}
            if(ips[0]==null || ips[1]==null)return Error("REFERENCE_RECONCILE_IP_CONFLICT","Missing transferred interruption");
            trial.LockAllObjects();for(int pin=0;pin<2;pin++)RefOrientIP(trial,ips[pin],contact,pin);
            using(var g=new Generate())g.Connections(trial,false);
            if(!expected.SetEquals(ChineseEdges(trial)))return Error("REFERENCE_RECONCILE_ROUTE_MISMATCH","Orientation repair did not produce full expected graph");
            var logical=RefReadEndpoints(trial);RefDocument(trial,page,FindTrialPage(trial,"/20"),FindTrialPage(trial,"/22"),FindTrialPage(trial,"/23"),expected.Count);var pageMap=RefPageOrder(trial);
            var endpoints=new Dictionary<string,object>();foreach(var pair in logical)endpoints[pair.Key]=new{object_id=pair.Value.F.ObjectIdentifier,type_id=pair.Value.F.TypeIdentifier,pin_index=pair.Value.Pin,tag=pair.Key.Split('.')[0],display_designation=pair.Value.F.Properties.FUNC_CONNECTIONDESIGNATION[pair.Value.Pin+1].ToString()};
            if(!expected.SetEquals(ChineseEdges(trial)))return Error("REFERENCE_RECONCILE_FINAL_GRAPH_CHANGED","Document order changed connectivity");
            string original=File.ReadAllText(record,Encoding.UTF8);File.WriteAllText(Path.Combine(ReferenceRoot,@"artifacts\reference_before_native_applied.json"),original,Encoding.UTF8);
            var applied=(Dictionary<string,object>)serializer.DeserializeObject(original);applied["expected_native_edges"]=expected;applied["native_edges"]=expected.Count;applied["reference_revision"]="reference-interfaces-1";File.WriteAllText(record,serializer.Serialize(applied),Encoding.UTF8);
            var result=new Dictionary<string,object>{{"revision","reference-interfaces-1"},{"plan_sha256",ReferencePlanHash},{"native_edges",expected.Count},{"expected_native_edges",expected},{"terminal_positions",58},{"logical_native_endpoints",endpoints},{"page_map",pageMap},{"pages",23},{"reference_connections_complete",true},{"orientation_reconciled",true},{"physical_ratings_verified",false},{"production_release_allowed",false}};
            File.WriteAllText(marker,serializer.Serialize(result),Encoding.UTF8);return Ok(result);
        }
        private static TerminalStrip RefStrip(Project p,Page definition,string tag,double x,double y)
        {
            var strip=new TerminalStrip();strip.Create(definition);strip.Name=tag;strip.VisibleName=tag;
            var v=new SymbolVariant();v.Initialize(new Eplan.EplApi.DataModel.MasterData.Symbol(new Eplan.EplApi.DataModel.MasterData.SymbolLibrary(p,"SPECIAL"),"TDEF"),0);strip.SetSymbolVariant(v,true);strip.Location=new PointD(x,y);return strip;
        }
        private static Terminal RefTerminal(Project p,TerminalStrip strip,Page page,int n,double x,double y)
        {var t=new Terminal();t.Create(strip,page,PhaseVariant(p,"X"));t.Properties.FUNC_PINORTERMINALNUMBER=n.ToString();t.VisibleName=n==1?strip.VisibleName:"";t.Location=new PointD(x,y);t.Pins[0].IsExtern=false;t.Pins[1].IsExtern=false;return t;}
        private Dictionary<string,object> InspectTrialReferenceInterfaces(ProjectManager pm,Project[] projects)
        {
            Project trial=null;string path=Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk");foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;
            if(trial==null)trial=pm.OpenProject(path);
            var rows=new List<object>();foreach(string name in new[]{"R","S","O","SSA","DC"})
            {try{var v=PhaseVariant(trial,name);var pins=new List<object>();foreach(var pin in v.ConnectionPoints)pins.Add(new{index=pin.Index,x=pin.Location.X,y=pin.Location.Y,direction=pin.Direction.ToString()});rows.Add(new{symbol=name,pins=pins});}catch(Exception ex){rows.Add(new{symbol=name,error=ex.Message});}}
            return Ok(new{symbols=rows,native_edges=ChineseEdges(trial).Count,write_performed=false});
        }
        private Dictionary<string,object> CompleteTrialReferenceInterfaces(ProjectManager pm,Project[] projects)
        {
            string planFile=Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces.plan.json"),record=Path.Combine(ReferenceRoot,@"artifacts\three_phase_applied.json"),marker=Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces_applied.json"),partial=Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces_partial.json");
            if(FileSha256(planFile)!=ReferencePlanHash)return Error("REFERENCE_PLAN_HASH_MISMATCH","Pinned reference plan differs");
            var serializer=new JavaScriptSerializer();var plan=(Dictionary<string,object>)serializer.DeserializeObject(File.ReadAllText(planFile,Encoding.UTF8));
            Project trial=null;string path=Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk");foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;if(trial==null)trial=pm.OpenProject(path);
            var applied=(Dictionary<string,object>)serializer.DeserializeObject(File.ReadAllText(record,Encoding.UTF8));var before=ChineseEdges(trial);var expected=new SortedSet<string>();foreach(object e in (object[])applied["expected_native_edges"])expected.Add(Convert.ToString(e));
            if(!expected.SetEquals(before))return Error("REFERENCE_GRAPH_CONFLICT","Preserve changed native circuit");
            if(File.Exists(marker))return Ok(new{already_applied=true,native_edges=before.Count,project_modified=false});
            if(File.Exists(partial))return Error("REFERENCE_PARTIAL_REQUIRES_RECONCILIATION","Inspect captured partial state before retry");
            if(before.Count!=123 || FileSha256(record)!=Convert.ToString(plan["baseline_applied_sha256"]) || FileSha256(Path.Combine(ReferenceRoot,@"artifacts\motor_forward_reverse.design.json"))!=Convert.ToString(plan["baseline_model_sha256"]))return Error("REFERENCE_BASELINE_STALE","Design or native revision changed");
            for(int n=19;n<=23;n++)if(FindTrialPage(trial,"/"+n)!=null)return Error("REFERENCE_PAGE_CONFLICT","Preserve existing new page");
            var rVariant=PhaseVariant(trial,"R");if(rVariant.ConnectionPoints.Length!=2)return Error("REFERENCE_SYMBOL_MAPPING_CONFLICT","Expected installed two-pin resistor");
            var old=new Dictionary<string,Function>();foreach(string role in new[]{"CH_A_OUT","CH_A_RETURN","CH_B_OUT","CH_B_RETURN","PWR_PLUS","PWR_0V","SAFE_IN","SAFE_OUT","SAFE_RETURN","STATUS","EDM"})old[role]=PhaseRole(trial,"SR1","ROLE_"+role+"_TBD");
            foreach(string role in new[]{"SAFE_RETURN","STATUS","EDM"})if(old[role].Connections.Length!=0)return Error("REFERENCE_ROLE_OCCUPIED","Preserve previously wired "+role);
            var ka=new Function[3];for(int i=0;i<3;i++){ka[i]=FindTrialFunction(FindTrialPage(trial,"/7"),"KA"+(i+1),"S");if(ka[i]==null || ka[i].Connections.Length!=0)return Error("REFERENCE_CONTACT_CONFLICT","Preserve KA contact wiring");}
            string originalRecord=File.ReadAllText(record,Encoding.UTF8),stage="preflight";bool mutated=false;
            var logical=new Dictionary<string,RefEnd>();
            try
            {
                trial.LockAllObjects();mutated=true;stage="create reference pages";
                Page s=PhasePage(trial,19,"安全继电器厂家端子及监控复位"),v=PhasePage(trial,20,"V20控制端子与状态反馈"),d=PhasePage(trial,21,"接口电源及内部激励分配"),param=PhasePage(trial,22,"参考器件参数与验证要求");
                var bomProps=new PagePropertyList();bomProps.PAGE_COUNTER=23;var bom=new Page();bom.Create(trial,DocumentTypeManager.DocumentType.Graphics,bomProps);var bomTitle=new MultiLangString();bomTitle.AddString(ISOCode.Language.L_zh_CN,"参考BOM增补与安装约束");bom.Properties.PAGE_NOMINATIOMN=bomTitle;
                stage="map safety reference ports";
                string[] roles={"PWR_PLUS","PWR_0V","CH_A_OUT","CH_A_RETURN","CH_B_OUT","CH_B_RETURN"},labels={"A1","A2","T1","IN1","T2","IN2"},names={"PWR_PLUS_ROLE","PWR_0V_ROLE","CH_A_OUT","CH_A_RETURN","CH_B_OUT","CH_B_RETURN"};
                for(int i=0;i<roles.Length;i++){RefMove(old[roles[i]],s,35+i*45,215);RefLabel(old[roles[i]],labels[i]);logical["SR1."+names[i]]=new RefEnd(old[roles[i]],0);}
                var box=FindTrialFunction(FindTrialPage(trial,"/5"),"SR1","DC");if(box!=null){box.Page=s;box.SetLogicalArea(new PointD(20,195),new PointD(290,228));ChineseHideLongFunctionText(box);}
                var srOut=PhaseNewFunction(trial,s,"SR1","S",50,135);RefLabel(srOut,"13","14");
                RefTransfer(trial,old["SAFE_IN"],srOut,0,expected);RefTransfer(trial,old["SAFE_OUT"],srOut,1,expected);
                logical["SR1.SAFE_IN_ROLE"]=new RefEnd(srOut,0);logical["SR1.SAFE_OUT"]=new RefEnd(srOut,1);
                old["SAFE_RETURN"].Remove();old["STATUS"].Remove();
                var srStatus=PhaseNewFunction(trial,s,"SR1","S",130,135);RefLabel(srStatus,"23","24");logical["SR1.STATUS_COMMON_ROLE"]=new RefEnd(srStatus,0);logical["SR1.STATUS"]=new RefEnd(srStatus,1);
                RefMove(old["EDM"],s,310,65);RefLabel(old["EDM"],"INF/S");logical["SR1.EDM_RETURN"]=new RefEnd(old["EDM"],0);
                var t4=EnsureTrialRolePoint(trial,s,"SR1","T4",0,245,65);logical["SR1.EDM_SEND"]=new RefEnd(t4,0);
                var t3=EnsureTrialRolePoint(trial,s,"SR1","T3",0,300,215);var in3=EnsureTrialRolePoint(trial,s,"SR1","IN3",0,350,215);logical["SR1.TEST3"]=new RefEnd(t3,0);logical["SR1.INPUT3"]=new RefEnd(in3,0);
                var feedback=PhaseNewFunction(trial,s,"KM0","O",270,135);RefLabel(feedback,"22","21");logical["KM0.EDM_IN"]=new RefEnd(feedback,1);logical["KM0.EDM_OUT"]=new RefEnd(feedback,0);
                var reset=PhaseNewFunction(trial,s,"SB5","SSA",325,135);reset.IsMainFunction=true;RefLabel(reset,"NO_IN_TBD","NO_OUT_TBD");logical["SB5.NO_IN"]=new RefEnd(reset,0);logical["SB5.NO_OUT"]=new RefEnd(reset,1);
                var r=PhaseNewFunction(trial,s,"R1","R",195,135);r.IsMainFunction=true;RefLabel(r,"1","2");logical["R1.IN"]=new RefEnd(r,0);logical["R1.OUT"]=new RefEnd(r,1);
                stage="map V20 ports";
                string[] vfRoles={"13","14","12","8","9","10","15+","16-"};double[] xs={40,90,140,190,240,290,40,90};
                var vf=new Dictionary<string,Function>();for(int i=0;i<vfRoles.Length;i++)vf[vfRoles[i]]=EnsureTrialRolePoint(trial,v,"VFD1",vfRoles[i],0,xs[i],i<6?215:85);
                var vfFault=PhaseNewFunction(trial,v,"VFD1","S",260,80);RefLabel(vfFault,"19","18");
                logical["VFD1.DI_SUPPLY_ROLE"]=new RefEnd(vf["13"],0);logical["VFD1.CONTROL_0V"]=new RefEnd(vf["14"],0);logical["VFD1.DI_REFERENCE_ROLE"]=new RefEnd(vf["12"],0);
                logical["VFD1.DI1"]=new RefEnd(vf["8"],0);logical["VFD1.DI2"]=new RefEnd(vf["9"],0);logical["VFD1.RESET"]=new RefEnd(vf["10"],0);
                logical["VFD1.READY_COMMON_ROLE"]=new RefEnd(vf["15+"],0);logical["VFD1.READY"]=new RefEnd(vf["16-"],0);logical["VFD1.FAULT_COMMON_ROLE"]=new RefEnd(vfFault,0);logical["VFD1.FAULT"]=new RefEnd(vfFault,1);
                for(int i=0;i<3;i++){RefMove(ka[i],v,190+i*50,145);RefLabel(ka[i],"13","14");}
                foreach(Function f in FindTrialPage(trial,"/7").Functions)if(f.VisibleName=="KA1" || f.VisibleName=="KA2" || f.VisibleName=="KA3")
                {if(f.SymbolVariant.SymbolName=="K")RefLabel(f,"A2(-)","A1(+)");if(f.SymbolVariant.SymbolName=="O")RefLabel(f,"22","21");}
                stage="extend protected external signal supply";
                var fu2=FindTrialFunction(FindTrialPage(trial,"/3"),"FU2","FA1");var supply=PhaseReadGroup("X9P","RP",fu2,1,null);
                foreach(var target in supply.Targets)if(!expected.Remove(PhaseEdgeKey(fu2,1,target.Function,target.Pin)))throw new InvalidOperationException("External supply baseline changed");
                foreach(RefEnd target in new[]{logical["SR1.STATUS_COMMON_ROLE"],logical["VFD1.READY_COMMON_ROLE"],logical["VFD1.FAULT_COMMON_ROLE"]})
                    supply.Targets.Add(new PhaseTarget{Function=target.F,Pin=target.Pin,IP=AttachTrialInterruption(trial,target.F,target.Pin,"RP_NEW_"+supply.Targets.Count,16,false,101)});
                if(supply.Targets.Count!=5)throw new InvalidOperationException("Expected five protected signal supply targets");
                PhaseDistribute(trial,FindTrialPage(trial,"/9"),d,supply,expected,0);
                stage="return distribution";
                var zero=PhaseRole(trial,"PS1","ROLE_0V_TBD");var zeroIP=PhaseAttached(zero,0);if(!zeroIP.VisibleName.EndsWith("DC0_FEED",StringComparison.Ordinal))throw new InvalidOperationException("0V feed changed");
                var zeroStrip=RefStrip(trial,FindTrialPage(trial,"/9"),"X9M",65,150);var m1=RefTerminal(trial,zeroStrip,d,1,30,157);var m2=RefTerminal(trial,zeroStrip,d,2,62,157);
                AttachTrialInterruption(trial,m1,0,"DC0_FEED",20,false,310);expected.Add(PhaseEdgeKey(zero,0,m1,0));
                var kmCoil=FindTrialFunction(FindTrialPage(trial,"/5"),"KM0","K");RefFork(trial,new RefEnd(m1,1),new RefEnd(kmCoil,1),new RefEnd(m2,0),"RM_D1",expected);RefWire(trial,new RefEnd(m2,1),logical["R1.OUT"],"RM_D2",expected);
                stage="internal V20 DI excitation";
                var driveStrip=RefStrip(trial,FindTrialPage(trial,"/9"),"X10P",110,150);var p1=RefTerminal(trial,driveStrip,d,1,30,79);var p2=RefTerminal(trial,driveStrip,d,2,62,79);
                RefWire(trial,logical["VFD1.DI_SUPPLY_ROLE"],new RefEnd(p1,0),"VP_FEED",expected);RefFork(trial,new RefEnd(p1,1),new RefEnd(ka[0],0),new RefEnd(p2,0),"VP_D1",expected);RefFork(trial,new RefEnd(p2,1),new RefEnd(ka[1],0),new RefEnd(ka[2],0),"VP_D2",expected);
                RefWire(trial,logical["VFD1.CONTROL_0V"],logical["VFD1.DI_REFERENCE_ROLE"],"VCOM",expected);
                for(int i=0;i<3;i++)RefWire(trial,new RefEnd(ka[i],1),new RefEnd(vf[(8+i).ToString()],0),"VDI"+(i+1),expected);
                stage="status and monitored reset";
                var inputs=new Function[3];for(int i=0;i<3;i++)foreach(Function f in FindTrialPage(trial,"/6").Functions)if(f.SymbolVariant!=null && f.SymbolVariant.SymbolName=="PLCCP" && f.Properties.FUNC_PLCADDRESS.ToString()=="I0."+(4+i))inputs[i]=f;
                foreach(Function f in inputs)if(f==null)throw new InvalidOperationException("Missing PLC status input");
                RefFork(trial,logical["SR1.STATUS"],new RefEnd(inputs[0],0),logical["R1.IN"],"SROK",expected);
                RefWire(trial,logical["VFD1.READY"],new RefEnd(inputs[1],0),"VREADY",expected);RefWire(trial,logical["VFD1.FAULT"],new RefEnd(inputs[2],0),"VFAULT",expected);
                RefWire(trial,logical["SR1.EDM_SEND"],logical["KM0.EDM_IN"],"EDM1",expected);RefWire(trial,logical["KM0.EDM_OUT"],logical["SB5.NO_IN"],"EDM2",expected);RefWire(trial,logical["SB5.NO_OUT"],logical["SR1.EDM_RETURN"],"EDM3",expected);RefWire(trial,logical["SR1.TEST3"],logical["SR1.INPUT3"],"SR3",expected);
                ChineseText(d,20,182,"X9M 外部0V返回；与VFD内部14号0V不直接并接",2.2);ChineseText(d,20,104,"X10P 仅V20内部13号24V激励；禁止给继电器线圈供电",2.2);
                int index=0;foreach(string tag in new[]{"X5L","X5N","X7PE","X6P","X6M","X8P","X9P","X9M","X10P"})
                {foreach(TerminalStrip strip in FindTrialPage(trial,"/9").TerminalStrips)if(strip.VisibleName==tag)strip.Location=new PointD(20+(index%3)*45,210-(index/3)*30);index++;}
                stage="generate and verify full native edge set";using(var g=new Generate())g.Connections(trial,false);
                var actual=ChineseEdges(trial);if(!expected.SetEquals(actual))throw new InvalidOperationException("Reference route set mismatch: expected "+expected.Count+", actual "+actual.Count);
                stage="reference notes and final document order";
                RefDocument(trial,s,v,param,bom,expected.Count);
                var pageMap=RefPageOrder(trial);
                var endpoints=new Dictionary<string,object>();foreach(var pair in logical)endpoints[pair.Key]=new{object_id=pair.Value.F.ObjectIdentifier,type_id=pair.Value.F.TypeIdentifier,pin_index=pair.Value.Pin,tag=pair.Key.Split('.')[0],display_designation=pair.Value.F.Properties.FUNC_CONNECTIONDESIGNATION[pair.Value.Pin+1].ToString()};
                if(!expected.SetEquals(ChineseEdges(trial)))throw new InvalidOperationException("Reference document generation changed graph");
                File.WriteAllText(Path.Combine(ReferenceRoot,@"artifacts\reference_before_native_applied.json"),originalRecord,Encoding.UTF8);
                applied["expected_native_edges"]=expected;applied["native_edges"]=expected.Count;applied["reference_revision"]="reference-interfaces-1";File.WriteAllText(record,serializer.Serialize(applied),Encoding.UTF8);
                var result=new Dictionary<string,object>{{"revision","reference-interfaces-1"},{"plan_sha256",ReferencePlanHash},{"native_edges",expected.Count},{"expected_native_edges",expected},{"terminal_positions",58},{"logical_native_endpoints",endpoints},{"page_map",pageMap},{"pages",23},{"reference_connections_complete",true},{"physical_ratings_verified",false},{"production_release_allowed",false}};
                File.WriteAllText(marker,serializer.Serialize(result),Encoding.UTF8);return Ok(result);
            }
            catch(Exception ex)
            {
                if(mutated)File.WriteAllText(partial,serializer.Serialize(new{stage=stage,error=ex.Message,expected=expected,actual=ChineseEdges(trial)}),Encoding.UTF8);
                return Error("REFERENCE_PARTIAL_OR_FAILED",stage+": "+ex.Message);
            }
        }
        private static void RefDocument(Project trial,Page s,Page v,Page param,Page bom,int count)
        {
            ChineseText(s,20,268,"SR1：SIRIUS 3SK1111-1AB30厂家端子参考；MONITORED监控启动",2.5);
            ChineseText(s,20,254,"A1/A2=24V/0V；T1/IN1、T2/IN2分别经SB0独立NC；T3-IN3按24V版本桥接",2.0);
            ChineseText(s,20,183,"13-14：KM0线圈供电；A2返回外部0V。23-24：高有效允许状态诊断。",2.0);
            ChineseText(s,20,171,"R1=2.2kΩ/1W并联PLC输入对0V，提供信号接点最小负载；实际DI兼容仍须核实。",2.0);
            ChineseText(s,235,183,"KM0：21-22镜像NC",2.0);ChineseText(s,305,171,"SB5 独立安全复位NO",2.0);
            ChineseText(s,20,75,"EDM：T4→KM0镜像NC→SB5→INF/S；禁止外部24V替代T4。",2.0);
            ChineseText(s,20,42,"SB5只恢复安全允许，不自动起动电机；单KM0不等同STO或已达PL/SIL。",2.0);
            ChineseText(v,20,268,"VFD1：SINAMICS V20三相系列控制端子参考；额定电压、功率、固件待最终确认",2.5);
            ChineseText(v,20,254,"13(+24V)仅激励三个KA独立NO；12(DIC)接14(内部0V)，不得与激励端混淆。",2.0);
            ChineseText(v,175,187,"KA1/2/3：13-14独立NO",2.0);
            ChineseText(v,20,54,"DO1：15+/16-隔离无源晶体管；外部24V经其传递READY。",2.0);
            ChineseText(v,205,44,"DO2：19=C、18=NO；17=NC未用。",2.0);
            ChineseText(v,20,30,"PLC M回外部0V；两路输出制式不同，VFD内部14号0V不因状态接口而并接PLC M。",2.0);
            string[] notes={"参考参数及选型约束（2019 V20 / 3SK1 / 3RT2官方资料）",
                "P0700=2，P0719=0，P0727=1：端子独立二线正反转；禁止两路命令同时有效。",
                "P0701=1（ON_FWD）；P0702=2（ON_REV）；P0703=9（故障确认）。",
                "P0731=52.0（READY）；P0732=52.3（FAULT）；P0748=2：故障输出高有效。",
                "P1210=0：禁止变频器自动再启动。普通停止采用OFF1，斜坡/停稳条件待验证。",
                "速度源：P1000=1（MOP），P1031=0，P1032=0（允许反转），P1040=正频率TBD。",
                "P1035/P1036按BOP MOP映射19.13/19.14；最终固件和速度给定均须调试核实。",
                "复位为独立单次脉冲；脉宽仍TBD，未知时Q0.2保持0；保持按钮不重复发脉冲。",
                "READY、故障、运行/零速是不同信号；无已验证停稳判据时全部启动/再启动禁止。",
                "CPU/DI/DO型号TBD；本图正端开关DO要求核实每点≥0.5A及整组感性负载能力。",
                "KA参考3RH2122-1BB40：24VDC、4W、2NO+2NC；NO/NC不得误用为共享COM。",
                "KM0接口参考3RT2016-1BB42：24VDC线圈、镜像NC21-22；容量仍按实际VFD校核。",
                "参考线圈端工作电压19.2–26.4V；PS1应调节24V并验证压降、容差、短路保护。",
                "R1：17V时约7.73mA，28.8V热校核约0.377W；这两个点不是线圈允许电压。",
                "线圈抑制附件按厂家选型；抑制会改变释放时间，不能据裸继电器时间设置换向间隔。",
                "SR1用MONITORED：双通道急停与独立SB5、镜像反馈完整；PLC只作状态诊断。",
                "接口参考设计不等于现场选型定案；电压、功率、保护配合、导线及安全评估仍待确认。",
                "原生导线逐项回读；无PLC下载、无设备送电或试转、无安全等级认证。"};
            for(int i=0;i<notes.Length;i++)ChineseText(param,20,268-i*12,notes[i],i==0?2.5:2.1);
            string[] additions={"参考BOM增补（与主BOM合并使用；完整CSV为当前设备需求清单）",
                "SB5：独立安全监控复位按钮，1NO，具体型号及开孔TBD。",
                "R1：2.2kΩ/1W，1只；PLC安全允许诊断输入的接点负载电阻，按环境降额。",
                "X9P：4位外部受保护24V分配；X9M：2位外部0V分配。",
                "X10P：2位V20内部24V激励分配；禁止与外部24V电源直接并联。",
                "SR1：3SK1111-1AB30参考；KA1/2/3：3RH2122-1BB40参考，共3只。",
                "KM0：3RT2016-1BB42只作端子/镜像触点参考，最终电流容量待VFD/负载确认。",
                "VFD1：V20三相系列，订货号/功率/额定电压TBD；PLC型号按用户要求TBD。",
                "端子位：X1=5，X2=10，X3=4，X4=4，X5L=4，X5N=3，X6P=3，X6M=9。",
                "端子位：X7PE=5，X8P=3，X9P=4，X9M=2，X10P=2；总计58位。",
                "安装图：新增分配端子和SB5必须纳入空间/线槽与门板开孔复核；不得按占位图加工。",
                "实际料号、触点负载、线圈抑制器、端子桥、线缆及线槽按选型计算，不按逻辑组数采购。"};
            for(int i=0;i<additions.Length;i++)ChineseText(bom,20,268-i*17,additions[i],i==0?2.5:2.2);
            var replacements=new Dictionary<string,string>{
                {"安全回路仍不完整：EDM、STATUS 公共端、手动 RESET、SAFE_RETURN 需按 SR1 选型闭合。","参考安全链端子与反馈/独立复位已绘制；厂家定义及条件见新增安全端子详图。"},
                {"本页角色名称不是实体针脚；KM0 停机性能/STO/所需安全等级尚未验证。","KM0线圈返回及镜像反馈已按参考端子连接；停机性能/STO/安全等级尚未验证。"},
                {"KM0：安全链控制接触器；位于变频器输入侧；线圈返回及反馈待闭合，不代表已验证安全停机","KM0：输入侧安全链控制接触器；返回及镜像反馈见详图；不代表已验证安全停机"},
                {"SR1：安全继电器；监视双通道急停；EDM反馈、安全输出返回及安全复位尚未闭合","SR1：参考3SK1111；双通道急停、镜像反馈及独立监控复位见详图"},
                {"SB2常闭停止：正常=1，按下/断线=0。I0.4至I0.6尚未闭合；I0.7备用，不作停止确认。","SB2常闭：正常1，按下/断线0；I0.4–I0.6按参考接口连接；I0.7仍备用。"},
                {"VFD 未接接口：DI 激励源/参考端、READY/FAULT 公共端及实际电平须按选型核实。","VFD接口采用V20参考：DI激励与参考分开，READY/FAULT按不同输出类型连接。"},
                {"KA1/KA2/KA3 的 NO 触点至 VFD 接口保持待定；不得将 DI COMMON 一概当作激励电源。","KA1/2/3独立NO已连接V20:8/9/10；激励来自13，12参考接14。"},
                {"13条安全/VFD连接意图仍未闭合；PLC供电和I/O标注完整不代表整机电气连接完整。","参考接口导线已回读；设备额定值、停稳许可及现场安全验证仍待完成。"},
                {"13条安全/VFD接口仍未闭合；尚无真实停稳反馈。原生检查通过也不能据此认定功能/安全验收通过。","参考端子接线已闭合；尚无已验证停稳判据；检查通过不等于现场安全验收。"},
                {"本图基本控制链尚未闭合：13条安全/VFD接口未接；厂家定义确认前不能直接补线。","参考控制链按厂家定义连接；现场设备版本、额定值及停稳条件未验证，禁止投运。"},
                {"待接SR1","SR1允许状态"},{"待接VFD1","V20反馈"},{"至VFD正转待接","至V20:8 正转"},{"至VFD反转待接","至V20:9 反转"},{"至VFD复位待接","至V20:10 复位"},
                {"SR1状态→DI（未接）","SR1:24→DI"},{"VFD READY→DI（未接）","V20:16−→DI"},{"VFD FAULT→DI（未接）","V20:18NO→DI"},
                {"位于变频器输入侧；线圈返回及反馈待闭合，不代表已验证安全停机","位于VFD输入侧；A2回0V、镜像NC入EDM；安全性能待验证"},
                {"监视双通道急停；EDM反馈、安全输出返回及安全复位尚未闭合","监视双通道急停，EDM、独立SB5与输出返回按厂家参考连接"}};
            foreach(Page p in trial.Pages)
            {
                var remove=new List<DrawingText>();foreach(Placement placement in p.AllGraphicalPlacements)
                {
                    var t=placement as DrawingText;if(t==null)continue;string old=t.Contents.GetString(ISOCode.Language.L_zh_CN),value=old;
                    if(p.IdentifyingName=="/1" && (old.StartsWith("N061 ")||old.StartsWith("N062 ")||old.StartsWith("N063 ")||old.StartsWith("N064 ")||old.StartsWith("N065 ")||old.StartsWith("N066 ")||old.StartsWith("N067 ")||old.StartsWith("N076 ")||old.StartsWith("N077 ")||old.StartsWith("N078 ")||old.StartsWith("N079 ")||old.StartsWith("N080 ")||old.StartsWith("N083 ")))remove.Add(t);
                    if(replacements.ContainsKey(old))value=replacements[old];
                    if(old.StartsWith("三相改版：123条原生连接"))value="厂家参考接口闭合："+count+"条原生连接；最终额定值/停稳/安全性能仍待验证。";
                    if(old=="未闭合接口（不得按此直接接线）")value="参考选型与验证边界";
                    if(old.StartsWith("安全 EDM、STATUS 公共端、RESET 和输出返回接口未闭合"))value="SR1/V20参考端子已连接；按已下载官方版本核对，现场固件及选型须确认。";
                    if(old.StartsWith("共50个端子位："))value="共58个端子位；参考接口电源分配新增8位，详见增补BOM。";
                    if(value!=old){t.LockObject();var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,value);t.Contents=m;}
                }
                foreach(var t in remove)t.Remove();
            }
            ChineseText(FindTrialPage(trial,"/1"),220,220,"SR1：3SK1111-1AB30参考",2.0);ChineseText(FindTrialPage(trial,"/1"),220,209,"VFD1：V20三相系列，额定值TBD",2.0);ChineseText(FindTrialPage(trial,"/1"),220,198,"KA：24V独立NO/NC参考；SB5独立监控复位",2.0);ChineseText(FindTrialPage(trial,"/1"),220,187,"厂家端子图与参数表见目录；采购/制造仍待选型。",2.0);
        }
        private static Dictionary<string,int> RefPageOrder(Project trial)
        {
            int[] old={19,6,7,20,8,9,10,11,21,12,13,22,14,15,23,16,17,18};int[] next={6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23};var map=new Dictionary<string,int>();var pages=new Page[old.Length];
            for(int i=0;i<old.Length;i++){pages[i]=FindTrialPage(trial,"/"+old[i]);map[old[i].ToString()]=next[i];var temp=new PagePropertyList();temp.PAGE_COUNTER=110+i;pages[i].SetName(temp);}
            for(int i=0;i<pages.Length;i++){var props=new PagePropertyList();props.PAGE_COUNTER=next[i];pages[i].SetName(props);}
            foreach(Page p in trial.Pages)foreach(Placement placement in p.AllGraphicalPlacements)
            {var t=placement as DrawingText;if(t==null)continue;string oldText=t.Contents.GetString(ISOCode.Language.L_zh_CN);string value=Regex.Replace(oldText,@"(见|与)(\s*)/(\d{1,2})(?=\D|$)",m=>{int n=Int32.Parse(m.Groups[3].Value);return map.ContainsKey(n.ToString())?m.Groups[1].Value+m.Groups[2].Value+"/"+map[n.ToString()]:m.Value;});value=value.Replace("10-11、16页","12-14、21页").Replace("10/11页","12/13页");if(value!=oldText){var contents=new MultiLangString();contents.AddString(ISOCode.Language.L_zh_CN,value);t.Contents=contents;}}
            var cover=FindTrialPage(trial,"/1");var remove=new List<DrawingText>();foreach(Placement placement in cover.AllGraphicalPlacements){var t=placement as DrawingText;if(t!=null && Math.Abs(t.Location.X-25)<0.01 && t.Location.Y>=100 && t.Location.Y<=212 && Regex.IsMatch(t.Contents.GetString(ISOCode.Language.L_zh_CN),@"^\d{1,2}  "))remove.Add(t);}foreach(var t in remove)t.Remove();
            for(int n=2;n<=23;n++)ChineseText(cover,25,211-(n-2)*5.4,n+"  "+FindTrialPage(trial,"/"+n).Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN),1.9);
            return map;
        }
        private static void RefBox(Page p,double x1,double y1,double x2,double y2,string label)
        {var r=new DrawingRectangle();r.Create(p);r.SetArea(new PointD(x1,y1),new PointD(x2,y2));if(label!="")ChineseText(p,x1+2,y2-6,label,2.1);}
        private Dictionary<string,object> FinalizeTrialReferenceDrawing(ProjectManager pm,Project[] projects)
        {
            string marker=Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces_applied.json"),done=Path.Combine(ReferenceRoot,@"artifacts\reference_drawing_finalized.json");
            if(FileSha256(Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces.plan.json"))!=ReferencePlanHash || !File.Exists(marker))return Error("REFERENCE_FINALIZE_REVISION_REQUIRED","Pinned reference revision required");
            Project trial=null;string path=Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk");foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;if(trial==null)trial=pm.OpenProject(path);
            var serializer=new JavaScriptSerializer();var applied=(Dictionary<string,object>)serializer.DeserializeObject(File.ReadAllText(marker,Encoding.UTF8));var expected=new SortedSet<string>();foreach(object e in (object[])applied["expected_native_edges"])expected.Add(Convert.ToString(e));
            if(expected.Count!=151 || !expected.SetEquals(ChineseEdges(trial)))return Error("REFERENCE_FINALIZE_GRAPH_CONFLICT","Preserve changed circuit");
            if(File.Exists(done))return Ok(new{already_finalized=true,native_edges=151,project_modified=false});
            Page s=FindTrialPage(trial,"/6"),dist=FindTrialPage(trial,"/14"),cab=FindTrialPage(trial,"/22"),door=FindTrialPage(trial,"/23");
            if(s==null || dist==null || cab==null || door==null || cab.Functions.Length!=0 || !cab.Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN).Contains("柜内"))return Error("REFERENCE_FINALIZE_PAGE_CONFLICT","Expected reference page set");
            trial.LockAllObjects();
            foreach(Page page in trial.Pages)foreach(Function f in page.Functions)
            {var t=f as Terminal;if(t!=null && t.Name.IndexOf("-X9P:",StringComparison.Ordinal)>=0){t.Pins[0].IsExtern=false;t.Pins[1].IsExtern=false;}}
            string[] labels={"A1","A2","T1","IN1","T2","IN2"};
            foreach(string label in labels)
            {
                Function f=RefFind(trial,"SR1","DCP",label);var ip=PhaseAttached(f,0);var location=f.Location;
                var variant=new SymbolVariant();variant.Initialize(new Symbol(new SymbolLibrary(trial,"SPECIAL"),"DCP"),0);f.SetSymbolVariant(variant,true);RefLabel(f,label);
                ip=RefOrientIP(trial,ip,f,0);PhaseMoveIP(ip,f,0);
            }
            var box=FindTrialFunction(s,"SR1","DC");if(box!=null){box.SetLogicalArea(new PointD(20,195),new PointD(370,228));if(!box.UseLocalPropertyPlacements)box.SwitchLocalPropertyPlacements(true);foreach(var p in box.PropertyPlacements){p.LockObject();p.IsSetAsVisible=Placement.Visibility.Invisible;}}
            foreach(Placement p in dist.AllGraphicalPlacements){var t=p as DrawingText;if(t==null)continue;string text=t.Contents.GetString(ISOCode.Language.L_zh_CN);if(text.StartsWith("X9P RP ")||text.StartsWith("X9M 外部")||text.StartsWith("X10P 仅")){t.LockObject();t.Location=new PointD(210,t.Location.Y);}}
            var cover=FindTrialPage(trial,"/1");foreach(Placement p in cover.AllGraphicalPlacements)
            {var t=p as DrawingText;if(t==null)continue;string text=t.Contents.GetString(ISOCode.Language.L_zh_CN);double y=0;
                if(text.StartsWith("CPU/模块、VFD、SR1"))y=81;if(text.StartsWith("SR1/V20参考端子已连接"))y=70;if(text.StartsWith("无已验证停稳许可时禁止全部启动"))y=59;if(text.StartsWith("BOM 是设计需求表"))y=48;if(y>0){t.LockObject();t.Location=new PointD(25,y);}}
            foreach(Page page in trial.Pages)foreach(Placement p in page.AllGraphicalPlacements)
            {var t=p as DrawingText;if(t==null)continue;string text=t.Contents.GetString(ISOCode.Language.L_zh_CN),next=text;
                if(text=="原38组 + 新增6组分配端子；详见16页变更表；实际采购量、物料号和额定参数 TBD。")next="主设备表与第20页参考增补合并；采购料号及额定值仍待确认，完整清单见导出CSV。";
                if(text=="物料号" && (page.IdentifyingName=="/18" || page.IdentifyingName=="/19"))next="采购料号";
                if(text=="KA线圈/常开/常闭触点使用A1/A2、NO、NC逻辑角色+TBD；实体编号仍待选型。")next="KA已按3RH参考标注A1/A2、NO13-14、NC21-22；最终实物、抑制器与输出兼容性须核对。";
                if(next!=text){var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,next);t.Contents=m;}}
            // Rebuild this owned, graph-free cabinet concept page to include all
            // actual design groups. No dimensions or vendor article placements
            // are invented; electrical circuit objects are never removed here.
            var remove=new List<Placement>();foreach(Placement p in cab.AllGraphicalPlacements)if(p is DrawingText || p is DrawingRectangle)remove.Add(p);foreach(var p in remove)p.Remove();
            ChineseText(cab,20,268,"柜内二维完整排布参考（58端子位及新增接口器件）",3.2);ChineseText(cab,20,254,"本页为包络排布；实际器件外形、柜体尺寸、安装间距和线槽规格须按最终选型验证。",2.2);
            RefBox(cab,30,20,260,240,"");RefBox(cab,35,25,43,233,"");RefBox(cab,247,25,255,233,"");
            foreach(double y in new[]{196.0,151.0,99.0,58.0})RefBox(cab,43,y,247,y+8,"");
            string[] top={"QS1","QF0","QF1","QF2","QF3","QF4","PS1"};for(int i=0;i<top.Length;i++)RefBox(cab,50+i*27,210,73+i*27,233,top[i]);
            RefBox(cab,50,165,100,190,"PLC1");RefBox(cab,105,165,135,190,"SR1");RefBox(cab,140,165,170,190,"KM0");RefBox(cab,175,165,240,190,"KA1 / KA2 / KA3");
            RefBox(cab,50,115,105,143,"FU1 / FU2 / FU3");RefBox(cab,110,115,127,143,"R1");RefBox(cab,135,110,240,145,"VFD1");
            for(int i=0;i<4;i++)RefBox(cab,50+i*47,77,92+i*47,94,"X"+(i+1));
            string[] lower={"X5L","X5N","X6P","X6M","X7PE","X8P","X9P","X9M","X10P"};for(int i=0;i<lower.Length;i++){int row=i/5,col=i%5;RefBox(cab,50+col*38,40-row*16,84+col*38,54-row*16,lower[i]);}
            RefBox(cab,50,67,240,72,"");ChineseText(cab,275,72,"PE汇流排：保护导体连续性与附件待实物核实",2.0);
            RefBox(cab,280,222,395,240,"EL1 柜内照明");RefBox(cab,280,180,333,210,"FAN1");RefBox(cab,340,180,395,210,"TS1");
            string[] installation={"动力、VFD输出与24V信号分区走线","VFD散热距离/电缆屏蔽按最终型号手册","9组分配端子全部列入；内外24V不得误并","R1安装需通风、固定、绝缘及温升降额","PLC实体模块TBD，预留更换及端子操作空间","线槽填充率、弯曲半径、导轨长度待核算","包络图不是实物二维宏或加工开孔图"};for(int i=0;i<installation.Length;i++)ChineseText(cab,275,157-i*12,installation[i],2.0);
            RefBox(door,155,44,187,71,"SB5");ChineseText(door,159,51,"安全复位",2.2);ChineseText(door,300,72,"SB5独立于SB4；安全复位不直接运行电机",2.0);
            using(var g=new Generate())g.Connections(trial,false);
            if(!expected.SetEquals(ChineseEdges(trial)))return Error("REFERENCE_FINALIZE_PARTIAL_GRAPH_CHANGED","Inspect reference graph before retry");
            var result=new{native_edges=151,terminal_positions=58,external_internal_terminal_flags_fixed=4,cabinet_groups_complete=true,door_SB5_added=true,physical_layout_dimensions_verified=false,production_release_allowed=false};File.WriteAllText(done,serializer.Serialize(result),Encoding.UTF8);return Ok(result);
        }
    }
}
