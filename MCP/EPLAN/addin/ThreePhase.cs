using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.MasterData;
using Eplan.EplApi.DataModel.EObjects;
using Eplan.EplApi.HEServices;
using DrawingText=Eplan.EplApi.DataModel.Graphics.Text;

namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private const string ThreePhasePlanHash="84074eac1e1fbd426ca28d6c91582f9f4e8e078bb9c457b50db83e2d2408dbfb";
        private static SymbolVariant PhaseVariant(Project project,string symbol)
        {var v=new SymbolVariant();v.Initialize(new Symbol(new SymbolLibrary(project,"GB_symbol"),symbol),0);return v;}

        private static void PhaseSetDefinition(Project project,Function function,string symbol)
        {
            var s=new Symbol(new SymbolLibrary(project,"GB_symbol"),symbol);
            function.Properties.FUNC_CATEGORY_GROUP_ID=s.Properties.FUNC_CATEGORY_GROUP_ID.ToString();
            function.SetSymbolVariant(PhaseVariant(project,symbol),true);
            int required=symbol=="FA4"?8:6;
            if(function.Pins.Length!=required)throw new InvalidOperationException(symbol+" function definition did not acquire "+required+" pins");
        }

        private static Dictionary<string,object> PhaseFinalize(Project trial,Dictionary<string,object> plan,SortedSet<string> expected)
        {
            int labels=0;
            foreach(Page page in trial.Pages)foreach(Function f in page.Functions)foreach(Pin pin in f.Pins)
                if(!(f is Terminal) && !String.IsNullOrEmpty(pin.Designation) &&
                    (String.IsNullOrWhiteSpace(f.Properties.FUNC_CONNECTIONDESIGNATION[pin.Index+1].ToString()) || f.Properties.FUNC_CONNECTIONDESIGNATION[pin.Index+1].ToString()==pin.Designation))
                {f.Properties.FUNC_CONNECTIONDESIGNATION[pin.Index+1]=pin.Designation;labels++;}
            // The design contract already distinguishes coil/NO/NC logical roles.
            // Use those roles with TBD, never guessed manufacturer pin numbers.
            Page outputs=FindTrialPage(trial,"/7");
            foreach(Function f in outputs.Functions)
                if(f.VisibleName=="KA1" || f.VisibleName=="KA2" || f.VisibleName=="KA3")
                {
                    string symbol=f.SymbolVariant.SymbolName;
                    if(symbol=="K")PhaseRoleLabel(f,"A2_TBD","A1_TBD");
                    if(symbol=="S")PhaseRoleLabel(f,"NO_IN_TBD","NO_OUT_TBD");
                    if(symbol=="O")PhaseRoleLabel(f,"NC_OUT_TBD","NC_IN_TBD");
                }
            // These groups are cabinet-internal distribution terminals. Inter-terminal
            // chain conductors must use the same internal side at both ends; retain
            // untouched field-facing ports on the existing boundary terminals.
            foreach(Page page in trial.Pages)foreach(Function f in page.Functions)
            {
                var terminal=f as Terminal;if(terminal==null)continue;
                bool internalGroup=false;foreach(string tag in new[]{"X5L","X5N","X6P","X6M","X7PE","X8P"})
                    if(terminal.Name.IndexOf("-"+tag+":",StringComparison.Ordinal)>=0)internalGroup=true;
                if(!internalGroup)continue;
                foreach(Pin pin in terminal.Pins)if(pin.Index==0 || pin.Index==1)pin.IsExtern=false;
                foreach(Connection edge in terminal.Connections)
                {
                    Terminal other=null;int index=-1;
                    if(edge.StartSymbolReference==terminal){other=edge.EndSymbolReference as Terminal;index=edge.EndIndex;}
                    if(edge.EndSymbolReference==terminal){other=edge.StartSymbolReference as Terminal;index=edge.StartIndex;}
                    if(other!=null && index>=0)other.Pins[index].IsExtern=false;
                }
            }
            foreach(int n in new[]{10,11})foreach(Placement placement in FindTrialPage(trial,"/"+n).AllGraphicalPlacements)
            {
                var text=placement as DrawingText;if(text==null)continue;
                string value=text.Contents.GetString(ISOCode.Language.L_zh_CN);
                if(value=="电源输入端子排（3端子位）")
                {text.LockObject();var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,"电源输入端子排（5端子位）");text.Contents=m;}
            }
            foreach(object item in (object[])plan["replacements"])
            {
                var n=(Dictionary<string,object>)item;Page page=FindTrialPage(trial,Convert.ToString(n["page"]));
                foreach(Placement placement in page.AllGraphicalPlacements)
                {var text=placement as DrawingText;if(text!=null && text.Contents.GetString(ISOCode.Language.L_zh_CN)==Convert.ToString(n["old"]))
                    {text.LockObject();var value=new MultiLangString();value.AddString(ISOCode.Language.L_zh_CN,Convert.ToString(n["new"]));text.Contents=value;
                     if(n.ContainsKey("x"))text.Location=new PointD(Convert.ToDouble(n["x"]),Convert.ToDouble(n["y"]));}}
            }
            if(FindTrialPage(trial,"/18")==null)PhasePage(trial,18,"三相改版物料变更与验收边界");
            foreach(object item in (object[])plan["notes"])
            {var n=(Dictionary<string,object>)item;ChineseText(FindTrialPage(trial,Convert.ToString(n["page"])),Convert.ToDouble(n["x"]),Convert.ToDouble(n["y"]),Convert.ToString(n["text"]),Convert.ToDouble(n["height"]));}
            foreach(string[] names in new[]{new[]{"L1_FEED","L1"},new[]{"N_FEED","N"},new[]{"AC_L2","L2"},new[]{"AC_L3","L3"},
                    new[]{"DRV_L1","D1"},new[]{"DRV_L2","D2"},new[]{"DRV_L3","D3"},new[]{"VFD_L1","V1"},new[]{"VFD_L2","V2"},new[]{"VFD_L3","V3"}})
                PhaseRenameProjectNet(trial,names[0],names[1]);
            foreach(int pageNumber in new[]{16,17})foreach(Placement placement in FindTrialPage(trial,"/"+pageNumber).AllGraphicalPlacements)
            {
                var text=placement as DrawingText;if(text==null)continue;
                string value=text.Contents.GetString(ISOCode.Language.L_zh_CN);
                string[] tags=pageNumber==16?new[]{"X5L","X5N","X7PE"}:new[]{"X6P","X6M","X8P"};
                string[] meanings=pageNumber==16?new[]{"L1","N","PE"}:new[]{"+24V","0V","按钮电源"};
                for(int row=0;row<3;row++)if(value.StartsWith(tags[row]+" ") && value.Contains("分配"))
                {
                    text.LockObject();var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,tags[row]+" "+meanings[row]+"分配");text.Contents=m;
                    text.Location=new PointD(330,250-row*78);
                    ChineseText(FindTrialPage(trial,"/"+pageNumber),330,238-row*78,"各连接点不超过2个目标",2.0);
                    ChineseText(FindTrialPage(trial,"/"+pageNumber),330,226-row*78,"实体端子及附件TBD",2.0);
                }
            }
            var neutralPole=FindTrialFunction(FindTrialPage(trial,"/2"),"QS1","S");
            if(neutralPole!=null){if(!neutralPole.UseLocalPropertyPlacements)neutralPole.SwitchLocalPropertyPlacements(true);foreach(var p in neutralPole.PropertyPlacements){p.LockObject();p.IsSetAsVisible=Placement.Visibility.Invisible;}}
            ChineseText(FindTrialPage(trial,"/2"),90,204,"QS1 N极",2.2);
            ChineseText(FindTrialPage(trial,"/2"),90,196,"与三相主极联动",2.0);
            foreach(Placement placement in FindTrialPage(trial,"/1").AllGraphicalPlacements)
            {
                var text=placement as DrawingText;if(text==null)continue;
                if(text.Contents.GetString(ISOCode.Language.L_zh_CN).StartsWith("2026-10-21 核对："))
                {text.LockObject();var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,"三相改版：121条原生连接；13条安全/VFD接口待闭合；见16-18页。");text.Contents=m;}
                if(text.Contents.GetString(ISOCode.Language.L_zh_CN)=="2  AC220V 输入与分配")
                {text.LockObject();var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,"2  三相原电源输入与配电（电压TBD）");text.Contents=m;}
            }
            foreach(Page page in trial.Pages)foreach(Function f in page.Functions)
                if(!f.Properties.FUNC_TEXT.IsEmpty)
                {
                    string old=f.Properties.FUNC_TEXT.ToString(ISOCode.Language.L_zh_CN);
                    string value=old.Replace("单相交流输入、三相交流输出","三相交流输入、三相交流输出").Replace("1=L、2=N、3=PE","1=L1、2=L2、3=L3、4=N、5=PE");
                    if(old!=value){var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,value);f.Properties.FUNC_TEXT=m;}
                }
            var title=new MultiLangString();title.AddString(ISOCode.Language.L_zh_CN,"三相原电源输入与配电（电压TBD）");FindTrialPage(trial,"/2").Properties.PAGE_NOMINATIOMN=title;
            ChineseText(FindTrialPage(trial,"/4"),310,190,"D1/D2/D3：保护后相线至KM0",2.1);
            ChineseText(FindTrialPage(trial,"/4"),310,180,"V1/V2/V3：KM0后至VFD输入",2.1);
            ChineseText(FindTrialPage(trial,"/18"),20,35,"KA线圈/常开/常闭触点使用A1/A2、NO、NC逻辑角色+TBD；实体编号仍待选型。",2.2);
            ChineseText(FindTrialPage(trial,"/18"),20,125,"共49个端子位：X1=5，X2=10，X3=4，X4=4；新增分配端子26位。",2.4);
            using(var generator=new Generate())generator.Connections(trial,false);
            if(!expected.SetEquals(ChineseEdges(trial)))throw new InvalidOperationException("Final annotation/role reconciliation altered electrical edges");
            return new Dictionary<string,object>{{"plan_sha256",ThreePhasePlanHash},{"native_edges",expected.Count},{"template_pin_labels_restored",labels},{"distribution_groups",6},{"connection_limits_increased",false},{"source_voltage_verified",false},{"physical_pin_mapping_verified",false},{"production_release_allowed",false},{"expected_native_edges",expected}};
        }

        private Dictionary<string,object> ReconcileTrialThreePhase(ProjectManager pm,Project[] projects)
        {
            string root=RuntimePath(@"");string path=Path.Combine(root,@"workspace\motor_forward_reverse_trial.elk");
            string planPath=Path.Combine(root,@"artifacts\three_phase_upgrade.plan.json");
            if(FileSha256(planPath)!=ThreePhasePlanHash)return Error("THREE_PHASE_PLAN_HASH_MISMATCH","Fixed plan changed");
            Project trial=null;foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;
            if(trial==null)trial=pm.OpenProject(path);
            try
            {
                if(File.Exists(Path.Combine(root,@"artifacts\three_phase_page_order.json")))
                {
                    var applied=(Dictionary<string,object>)new JavaScriptSerializer().DeserializeObject(File.ReadAllText(Path.Combine(root,@"artifacts\three_phase_applied.json"),Encoding.UTF8));
                    var pinned=new SortedSet<string>();foreach(object s in (object[])applied["expected_native_edges"])pinned.Add(Convert.ToString(s));
                    if(pinned.Count!=Convert.ToInt32(applied["native_edges"]) || !pinned.SetEquals(ChineseEdges(trial)))return Error("THREE_PHASE_RECONCILE_CONFLICT","Finalized graph changed");
                    applied["read_only_replay"]=true;applied["page_order_finalized"]=true;return Ok(applied);
                }
                var plan=(Dictionary<string,object>)new JavaScriptSerializer().DeserializeObject(File.ReadAllText(planPath,Encoding.UTF8));
                var rec=(Dictionary<string,object>)new JavaScriptSerializer().DeserializeObject(File.ReadAllText(Path.Combine(root,@"artifacts\three_phase_reconcile.json"),Encoding.UTF8));
                var expected=new SortedSet<string>();foreach(object s in (object[])rec["expected"])expected.Add(Convert.ToString(s));
                var current=ChineseEdges(trial);var checkpoint=new SortedSet<string>();foreach(object s in (object[])rec["actual"])checkpoint.Add(Convert.ToString(s));
                // Allow the fully corrected, same native edge set for verification replay.
                if(!checkpoint.SetEquals(current) && !expected.SetEquals(current))return Error("THREE_PHASE_RECONCILE_CONFLICT","Circuit changed since captured partial checkpoint");
                if(File.Exists(Path.Combine(root,@"artifacts\three_phase_page_order.json")))
                {
                    if(!expected.SetEquals(current))return Error("THREE_PHASE_RECONCILE_CONFLICT","Finalized graph changed");
                    var finalized=(Dictionary<string,object>)new JavaScriptSerializer().DeserializeObject(File.ReadAllText(Path.Combine(root,@"artifacts\three_phase_applied.json"),Encoding.UTF8));
                    finalized["read_only_replay"]=true;finalized["page_order_finalized"]=true;return Ok(finalized);
                }
                if(FindTrialPage(trial,"/16")==null || FindTrialPage(trial,"/17")==null)return Error("THREE_PHASE_RECONCILE_CONFLICT","Distribution pages missing");
                trial.LockAllObjects();
                PhaseSetDefinition(trial,FindTrialFunction(FindTrialPage(trial,"/2"),"QS1","Q3"),"Q3");
                PhaseSetDefinition(trial,FindTrialFunction(FindTrialPage(trial,"/2"),"QF0","FA4"),"FA4");
                PhaseSetDefinition(trial,FindTrialFunction(FindTrialPage(trial,"/2"),"QF1","FA3"),"FA3");
                using(var g=new Generate())g.Connections(trial,false);
                current=ChineseEdges(trial);if(!expected.SetEquals(current))
                {var missing=new SortedSet<string>(expected);missing.ExceptWith(current);var extra=new SortedSet<string>(current);extra.ExceptWith(expected);File.WriteAllText(Path.Combine(root,@"artifacts\three_phase_definition_reconcile.json"),new JavaScriptSerializer().Serialize(new{expected=expected,actual=current,missing=missing,extra=extra}));return Error("THREE_PHASE_RECONCILE_MISMATCH","Missing "+missing.Count+", extra "+extra.Count);}
                var result=PhaseFinalize(trial,plan,expected);File.WriteAllText(Path.Combine(root,@"artifacts\three_phase_applied.json"),new JavaScriptSerializer().Serialize(result),Encoding.UTF8);return Ok(result);
            }
            catch(Exception ex){return Error("THREE_PHASE_RECONCILE_FAILED",ex.Message);}
        }

        private static Function PhaseRole(Project project,string tag,string role)
        {
            Function result=null;
            foreach(Page p in project.Pages)foreach(Function f in p.Functions)
                if(f.SymbolVariant!=null && f.SymbolVariant.SymbolName=="DCP" &&
                    (f.VisibleName==tag || f.Name.IndexOf("-"+tag+":",StringComparison.Ordinal)>=0) &&
                    f.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString()==role)
                {if(result!=null)throw new InvalidOperationException("Ambiguous role "+role);result=f;}
            if(result==null)throw new InvalidOperationException("Missing role "+role);return result;
        }

        private static InterruptionPoint PhaseAttached(Function f,int pin)
        {
            InterruptionPoint result=null;
            foreach(var g in f.GraphicalConnections)
            {
                InterruptionPoint candidate=null;
                if(g.StartSymbolRef==f && g.StartConnectionPoint.Index==pin)candidate=g.EndSymbolRef as InterruptionPoint;
                if(g.EndSymbolRef==f && g.EndConnectionPoint.Index==pin)candidate=g.StartSymbolRef as InterruptionPoint;
                if(candidate!=null){if(result!=null && result.ObjectIdentifier!=candidate.ObjectIdentifier)throw new InvalidOperationException("Multiple attached interruptions");result=candidate;}
            }
            if(result==null)throw new InvalidOperationException("No unique interruption at "+f.Name+":"+pin);
            return result;
        }

        private static void PhaseMoveIP(InterruptionPoint ip,Function f,int pin)
        {
            PinBase point=null;foreach(PinBase p in f.GraphicalConnectionPoints)if(p.Index==pin)point=p;
            if(point==null)throw new InvalidOperationException("Pin geometry missing");
            double x=f.Location.X+point.Location.X,y=f.Location.Y+point.Location.Y;
            switch(point.Direction.ToString()){case "Up":y+=20;break;case "Down":y-=20;break;default:throw new InvalidOperationException("Unexpected phase pin direction");}
            ip.Location=new PointD(x,y);
        }

        private sealed class PhaseTarget
        {public Function Function;public int Pin;public InterruptionPoint IP;}
        private sealed class PhaseGroup
        {public string Tag,Prefix;public Function Root;public int Pin;public InterruptionPoint IP;public List<PhaseTarget> Targets=new List<PhaseTarget>();}

        private static PhaseGroup PhaseReadGroup(string tag,string prefix,Function root,int pin,Function exclude)
        {
            var group=new PhaseGroup{Tag=tag,Prefix=prefix,Root=root,Pin=pin,IP=PhaseAttached(root,pin)};
            foreach(Connection edge in root.Connections)
            {
                Function target=null;int index=0;
                if(edge.StartSymbolReference==root && edge.StartIndex==pin){target=edge.EndSymbolReference as Function;index=edge.EndIndex;}
                if(edge.EndSymbolReference==root && edge.EndIndex==pin){target=edge.StartSymbolReference as Function;index=edge.StartIndex;}
                if(target==null || target==exclude)continue;
                if(!edge.IsPlaced)throw new InvalidOperationException("Unplaced edge at distribution root");
                group.Targets.Add(new PhaseTarget{Function=target,Pin=index,IP=PhaseAttached(target,index)});
            }
            group.Targets.Sort((a,b)=>String.CompareOrdinal(a.Function.Name+":"+a.Pin,b.Function.Name+":"+b.Pin));
            if(group.Targets.Count<2 || group.Targets.Count>12)throw new InvalidOperationException("Unexpected distribution count "+prefix);
            return group;
        }

        private static void PhaseRenameProjectNet(Project project,string oldName,string newName)
        {foreach(Page p in project.Pages)foreach(Placement placement in p.AllPlacements){var ip=placement as InterruptionPoint;if(ip!=null && ip.VisibleName==oldName){ip.Name=newName;ip.VisibleName=newName;}}}

        private static void PhaseRoleLabel(Function f,string first,string second=null)
        {f.Properties.FUNC_CONNECTIONDESIGNATION[1]=first;if(second!=null)f.Properties.FUNC_CONNECTIONDESIGNATION[2]=second;}

        private static Function PhaseNewFunction(Project project,Page page,string tag,string symbol,double x,double y)
        {var f=new Function();f.Create(page,PhaseVariant(project,symbol));f.Name=tag;f.VisibleName=tag;f.IsMainFunction=false;f.Location=new PointD(x,y);return f;}

        private static Page PhasePage(Project p,int n,string title)
        {
            if(FindTrialPage(p,"/"+n)!=null)throw new InvalidOperationException("New distribution page already exists");
            var props=new PagePropertyList();props.PAGE_COUNTER=n;var page=new Page();page.Create(p,DocumentTypeManager.DocumentType.Circuit,props);
            var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,title);page.Properties.PAGE_NOMINATIOMN=m;return page;
        }

        private static string PhaseEdgeKey(SymbolReference a,int ai,SymbolReference b,int bi)
        {string x=a.TypeIdentifier+":"+a.ObjectIdentifier+":"+ai,y=b.TypeIdentifier+":"+b.ObjectIdentifier+":"+bi;return (String.CompareOrdinal(x,y)<0?x+"|"+y:y+"|"+x)+"|True";}

        private static void PhaseDistribute(Project project,Page definitionPage,Page page,PhaseGroup group,SortedSet<string> expected,int groupIndex)
        {
            var strip=new TerminalStrip();strip.Create(definitionPage);strip.Name=group.Tag;strip.VisibleName=group.Tag;
            var def=new SymbolVariant();def.Initialize(new Symbol(new SymbolLibrary(project,"SPECIAL"),"TDEF"),0);strip.SetSymbolVariant(def,true);
            strip.Location=new PointD(20+groupIndex*35,200);
            group.IP.Name=group.Prefix+"_FEED";group.IP.VisibleName=group.Prefix+"_FEED";group.IP.IsStarSource=true;
            int count=group.Targets.Count-1;Terminal previous=null;
            ChineseText(page,20,260-groupIndex%3*78,group.Tag+" "+group.Prefix+" 分配；每连接点最多2个导线目标；实体端子及桥接附件待选型",2.2);
            for(int i=0;i<count;i++)
            {
                var terminal=new Terminal();terminal.Create(strip,page,PhaseVariant(project,"X"));terminal.Properties.FUNC_PINORTERMINALNUMBER=(i+1).ToString();
                terminal.VisibleName=i==0?group.Tag:"";terminal.Location=new PointD(30+i*32,235-groupIndex%3*78);
                string feed=i==0?group.Prefix+"_FEED":group.Prefix+"_D"+i;
                AttachTrialInterruption(project,terminal,0,feed,20,false,300+i);
                string output=group.Prefix+"_D"+(i+1);AttachTrialInterruption(project,terminal,1,output,20,true,100);
                var target=group.Targets[i];target.IP.Name=output;target.IP.VisibleName=output;target.IP.IsStarSource=false;target.IP.Properties.INTERRUPTIONPOINT_SORT_CODE=101;
                expected.Add(PhaseEdgeKey(terminal,1,target.Function,target.Pin));
                if(previous==null)expected.Add(PhaseEdgeKey(group.Root,group.Pin,terminal,0));else expected.Add(PhaseEdgeKey(previous,1,terminal,0));
                previous=terminal;
            }
            var last=group.Targets[group.Targets.Count-1];last.IP.Name=group.Prefix+"_D"+count;last.IP.VisibleName=last.IP.Name;last.IP.IsStarSource=false;last.IP.Properties.INTERRUPTIONPOINT_SORT_CODE=102;
            expected.Add(PhaseEdgeKey(previous,1,last.Function,last.Pin));
        }

        private Dictionary<string,object> UpgradeTrialThreePhase(ProjectManager pm,Project[] projects)
        {
            string root=RuntimePath(@"");
            string planPath=Path.Combine(root,@"artifacts\three_phase_upgrade.plan.json");
            if(FileSha256(planPath)!=ThreePhasePlanHash)return Error("THREE_PHASE_PLAN_HASH_MISMATCH","Plan requires a compiled pinned revision");
            var plan=(Dictionary<string,object>)new JavaScriptSerializer().DeserializeObject(File.ReadAllText(planPath,Encoding.UTF8));
            if(FileSha256(Path.Combine(root,@"artifacts\motor_forward_reverse.design.json"))!=Convert.ToString(plan["base_model_sha256"]))return Error("THREE_PHASE_MODEL_STALE","Base model changed");
            Project trial=null;string path=Path.Combine(root,@"workspace\motor_forward_reverse_trial.elk");foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;
            if(trial==null)trial=pm.OpenProject(path);
            string stage="preflight";
            try
            {
                Page p2=FindTrialPage(trial,"/2"),p4=FindTrialPage(trial,"/4"),p9=FindTrialPage(trial,"/9");
                var qs=FindTrialFunction(p2,"QS1","Q2");var qf0=FindTrialFunction(p2,"QF0","FA2");var qf1=FindTrialFunction(p2,"QF1","FA2");
                if(qs==null || qf0==null || qf1==null)return Error("THREE_PHASE_BASE_CONFLICT","Expected original two-pole draft functions");
                var oldEdges=ChineseEdges(trial);if(oldEdges.Count!=88)return Error("THREE_PHASE_BASE_CONFLICT","Expected verified 88-edge checkpoint");
                var q3=PhaseVariant(trial,"Q3");var fa3=PhaseVariant(trial,"FA3");var fa4=PhaseVariant(trial,"FA4");
                foreach(var v in new[]{q3,fa3,fa4})foreach(PinBase p in v.ConnectionPoints)
                    if(Math.Abs(p.Location.X-8*(p.Index/2))>0.001 || Math.Abs(p.Location.Y-(p.Index%2==0?4:-4))>0.001 || p.Direction.ToString()!=(p.Index%2==0?"Up":"Down"))
                        return Error("THREE_PHASE_PIN_MAP_CHANGED",v.SymbolName);
                if(q3.ConnectionPoints.Length!=6 || fa3.ConnectionPoints.Length!=6 || fa4.ConnectionPoints.Length!=8)return Error("THREE_PHASE_PIN_MAP_CHANGED","Pole count");
                var neutral=FindTrialTerminal(trial,"X1","2");var pe=FindTrialTerminal(trial,"X1","3");var l1=FindTrialTerminal(trial,"X1","1");
                Function kmL=null,kmN=null;foreach(Function f in p4.Functions)if(f.VisibleName=="KM0" && f.SymbolVariant.SymbolName=="S")
                {string role=f.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString();if(role=="L_IN_TBD")kmL=f;else if(role=="N_IN_TBD")kmN=f;}
                if(kmL==null || kmN==null)return Error("THREE_PHASE_BASE_CONFLICT","KM0 phase contacts");
                var vfL=PhaseRole(trial,"VFD1","ROLE_L_TBD");var vfN=PhaseRole(trial,"VFD1","ROLE_N_TBD");
                var acL=PhaseReadGroup("X5L","L1",qf0,1,null);var acN=PhaseReadGroup("X5N","N",qf0,3,qf1);
                var plus=PhaseReadGroup("X6P","DC24",PhaseRole(trial,"PS1","ROLE_24V_TBD"),0,null);
                var zero=PhaseReadGroup("X6M","DC0",PhaseRole(trial,"PS1","ROLE_0V_TBD"),0,null);
                int pePin=-1;foreach(Connection e in pe.Connections){int n=e.StartSymbolReference==pe?e.StartIndex:e.EndIndex;if(pePin>=0 && pePin!=n)throw new InvalidOperationException("PE feed spans multiple pins");pePin=n;}
                var earth=PhaseReadGroup("X7PE","PE",pe,pePin,null);var button=PhaseReadGroup("X8P","PB24",FindTrialTerminal(trial,"X2","1"),1,null);
                var groups=new[]{acL,acN,plus,zero,earth,button};
                var qf1L2Input=PhaseAttached(qf1,2);var qf1L2Output=PhaseAttached(qf1,3);
                var phaseAffected=new HashSet<string>();foreach(var f in new[]{qs,qf0,qf1,kmL,kmN,vfL,vfN})phaseAffected.Add(f.TypeIdentifier+":"+f.ObjectIdentifier);
                var expected=new SortedSet<string>(oldEdges);
                foreach(Page page in trial.Pages)foreach(Function f in page.Functions)foreach(Connection e in f.Connections)
                {
                    bool affected=phaseAffected.Contains(e.StartSymbolReference.TypeIdentifier+":"+e.StartSymbolReference.ObjectIdentifier)||phaseAffected.Contains(e.EndSymbolReference.TypeIdentifier+":"+e.EndSymbolReference.ObjectIdentifier);
                    foreach(var g in groups)if((e.StartSymbolReference==g.Root && e.StartIndex==g.Pin)||(e.EndSymbolReference==g.Root && e.EndIndex==g.Pin))affected=true;
                    if(affected)expected.Remove(PhaseEdgeKey(e.StartSymbolReference,e.StartIndex,e.EndSymbolReference,e.EndIndex));
                }
                stage="native phase topology";trial.LockAllObjects();
                neutral.Properties.FUNC_PINORTERMINALNUMBER="4";pe.Properties.FUNC_PINORTERMINALNUMBER="5";
                PhaseSetDefinition(trial,qs,"Q3");PhaseSetDefinition(trial,qf0,"FA4");PhaseSetDefinition(trial,qf1,"FA3");
                neutral.Location=new PointD(74,240);pe.Location=new PointD(100,240);l1.Location=new PointD(50,240);
                var qsN=PhaseNewFunction(trial,p2,"QS1","S",74,200);PhaseRoleLabel(qsN,"N_IN_TBD","N_OUT_TBD");
                TerminalStrip inputStrip=null;foreach(TerminalStrip s in p9.TerminalStrips)if(s.VisibleName=="X1")inputStrip=s;
                for(int i=1;i<=2;i++){var t=new Terminal();t.Create(inputStrip,p2,PhaseVariant(trial,"X"));t.Properties.FUNC_PINORTERMINALNUMBER=(i+1).ToString();t.Location=new PointD(50+i*8,240);}
                acN.Pin=7;PhaseMoveIP(acN.IP,qf0,7);PhaseMoveIP(earth.IP,pe,pePin);
                PhaseMoveIP(qf1L2Input,qf1,2);PhaseMoveIP(qf1L2Output,qf1,3);
                foreach(string[] pair in new[]{new[]{"DRV_L","DRV_L1"},new[]{"DRV_N","DRV_L2"},new[]{"VFD_L","VFD_L1"},new[]{"VFD_N","VFD_L2"}})PhaseRenameProjectNet(trial,pair[0],pair[1]);
                qf1L2Input.Name="AC_L2";qf1L2Input.VisibleName="AC_L2";
                AttachTrialInterruption(trial,qf0,3,"AC_L2",20,true,100);AttachTrialInterruption(trial,qf0,5,"AC_L3",20,true,100);
                AttachTrialInterruption(trial,qf1,4,"AC_L3",20,false,101);AttachTrialInterruption(trial,qf1,5,"DRV_L3",20,true,100);
                PhaseRoleLabel(kmL,"L1_IN_TBD","L1_OUT_TBD");PhaseRoleLabel(kmN,"L2_IN_TBD","L2_OUT_TBD");PhaseRoleLabel(vfL,"ROLE_L1_TBD");PhaseRoleLabel(vfN,"ROLE_L2_TBD");
                var km3=PhaseNewFunction(trial,p4,"KM0","S",130,210);PhaseRoleLabel(km3,"L3_IN_TBD","L3_OUT_TBD");
                var vf3=EnsureTrialRolePoint(trial,p4,"VFD1","ROLE_L3_TBD",0,260,232);
                AttachTrialInterruption(trial,km3,0,"DRV_L3",20,false,101);AttachTrialInterruption(trial,km3,1,"VFD_L3",20,true,100);AttachTrialInterruption(trial,vf3,0,"VFD_L3",20,false,101);
                foreach(var f in new[]{kmL,kmN,km3})ChineseHideLongFunctionText(f);
                for(int i=0;i<3;i++){var t=FindTrialTerminal(trial,"X1",(i+1).ToString());expected.Add(PhaseEdgeKey(t,1,qs,2*i));expected.Add(PhaseEdgeKey(qs,2*i+1,qf0,2*i));}
                expected.Add(PhaseEdgeKey(neutral,1,qsN,0));expected.Add(PhaseEdgeKey(qsN,1,qf0,6));
                expected.Add(PhaseEdgeKey(qf0,3,qf1,2));expected.Add(PhaseEdgeKey(qf0,5,qf1,4));
                var contacts=new[]{kmL,kmN,km3};var vfds=new[]{vfL,vfN,vf3};for(int i=0;i<3;i++){expected.Add(PhaseEdgeKey(qf1,2*i+1,contacts[i],0));expected.Add(PhaseEdgeKey(contacts[i],1,vfds[i],0));}
                stage="native distribution terminals";var acPage=PhasePage(trial,16,"三相配电及PE分配端子");var dcPage=PhasePage(trial,17,"直流及按钮电源分配端子");
                for(int i=0;i<groups.Length;i++){Page page=i==0||i==1||i==4?acPage:dcPage;int row=i==0?0:i==1?1:i==4?2:i==2?0:i==3?1:2;PhaseDistribute(trial,p9,page,groups[i],expected,row);}
                stage="native connection regeneration";using(var g=new Generate())g.Connections(trial,false);
                var actual=ChineseEdges(trial);if(!expected.SetEquals(actual))
                {var missing=new SortedSet<string>(expected);missing.ExceptWith(actual);var extra=new SortedSet<string>(actual);extra.ExceptWith(expected);File.WriteAllText(Path.Combine(root,@"artifacts\three_phase_reconcile.json"),new JavaScriptSerializer().Serialize(new{expected=expected,actual=actual,missing=missing,extra=extra}));return Error("THREE_PHASE_PARTIAL_ROUTE_MISMATCH","Missing "+missing.Count+", extra "+extra.Count+"; inspect reconciliation before retry");}
                stage="restore verified symbol template labels";int labels=0;
                foreach(Page page in trial.Pages)foreach(Function f in page.Functions)foreach(Pin pin in f.Pins)
                    if(f.Properties.FUNC_CONNECTIONDESIGNATION[pin.Index+1].IsEmpty && !String.IsNullOrEmpty(pin.Designation))
                    {f.Properties.FUNC_CONNECTIONDESIGNATION[pin.Index+1]=pin.Designation;labels++;}
                stage="Chinese plan notes";
                foreach(object item in (object[])plan["replacements"])
                {
                    var n=(Dictionary<string,object>)item;Page page=FindTrialPage(trial,Convert.ToString(n["page"]));
                    foreach(Placement placement in page.AllGraphicalPlacements)
                    {var text=placement as DrawingText;if(text!=null && text.Contents.GetString(ISOCode.Language.L_zh_CN)==Convert.ToString(n["old"]))
                        {text.LockObject();var value=new MultiLangString();value.AddString(ISOCode.Language.L_zh_CN,Convert.ToString(n["new"]));text.Contents=value;
                         if(n.ContainsKey("x"))text.Location=new PointD(Convert.ToDouble(n["x"]),Convert.ToDouble(n["y"]));}}
                }
                PhasePage(trial,18,"三相改版物料变更与验收边界");
                foreach(object item in (object[])plan["notes"])
                {var n=(Dictionary<string,object>)item;ChineseText(FindTrialPage(trial,Convert.ToString(n["page"])),Convert.ToDouble(n["x"]),Convert.ToDouble(n["y"]),Convert.ToString(n["text"]),Convert.ToDouble(n["height"]));}
                var metadata=new Dictionary<string,object>{{"plan_sha256",ThreePhasePlanHash},{"native_edges",actual.Count},{"template_pin_labels_restored",labels},{"distribution_groups",6},{"connection_limits_increased",false},{"source_voltage_verified",false},{"physical_pin_mapping_verified",false},{"production_release_allowed",false},{"expected_native_edges",expected}};
                File.WriteAllText(Path.Combine(root,@"artifacts\three_phase_applied.json"),new JavaScriptSerializer().Serialize(metadata),Encoding.UTF8);
                return Ok(metadata);
            }
            catch(Exception ex){return Error("THREE_PHASE_PARTIAL_OR_FAILED",stage+": "+ex.Message);}
        }
        private Dictionary<string,object> ThreePhaseCatalog(ProjectManager pm,Project[] projects)
        {
            string path=RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial=null;foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;
            if(trial==null)trial=pm.OpenProject(path);
            var library=new SymbolLibrary(trial,"GB_symbol");
            var results=new List<Dictionary<string,object>>();
            foreach(string name in new[]{"Q3","Q4","FA3","FA4","S","X"})
            {
                try
                {
                    var symbol=new Symbol(library,name);var variant=new SymbolVariant();variant.Initialize(symbol,0);
                    var pins=new List<Dictionary<string,object>>();
                    foreach(PinBase pin in variant.ConnectionPoints)pins.Add(new Dictionary<string,object>{{"index",pin.Index},{"x",pin.Location.X},{"y",pin.Location.Y},{"direction",pin.Direction.ToString()}});
                    results.Add(new Dictionary<string,object>{{"symbol",name},{"points",pins},{"description",symbol.Properties.SYMB_DESC.ToString()}});
                }
                catch(Exception ex){results.Add(new Dictionary<string,object>{{"symbol",name},{"available",false},{"reason",ex.Message}});}
            }
            return Ok(new Dictionary<string,object>{{"catalog",results},{"project_modified",false}});
        }
    }
}
