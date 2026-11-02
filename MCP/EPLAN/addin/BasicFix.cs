using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.EObjects;
using Eplan.EplApi.HEServices;
using DrawingText=Eplan.EplApi.DataModel.Graphics.Text;
namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private Dictionary<string,object> RepairTrialBasicRequirements(ProjectManager pm,Project[] projects)
        {
            string root=RuntimePath(@"");
            string path=Path.Combine(root,@"workspace\motor_forward_reverse_trial.elk"),record=Path.Combine(root,@"artifacts\three_phase_applied.json"),marker=Path.Combine(root,@"artifacts\basic_requirements_fix.json");
            Project trial=null;foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;
            if(trial==null)trial=pm.OpenProject(path);
            if(File.Exists(Path.Combine(root,@"artifacts\basic_fix_partial.json")))return Error("BASIC_FIX_PARTIAL_REQUIRES_INSPECTION","Inspect captured partial state before retry");
            var serializer=new JavaScriptSerializer();
            var applied=(Dictionary<string,object>)serializer.DeserializeObject(File.ReadAllText(record,Encoding.UTF8));
            var expected=new SortedSet<string>();foreach(object s in (object[])applied["expected_native_edges"])expected.Add(Convert.ToString(s));
            var before=ChineseEdges(trial);
            if(!expected.SetEquals(before))return Error("BASIC_FIX_GRAPH_CONFLICT","Preserve changed circuit");
            if(File.Exists(marker))return Ok(new Dictionary<string,object>{{"already_applied",true},{"native_edges",before.Count},{"electrical_topology_changed",false}});
            if(before.Count!=121 || !File.Exists(Path.Combine(root,@"artifacts\three_phase_page_order.json")))return Error("BASIC_FIX_REVISION_REQUIRED","Expected finalized 121-edge baseline");
            Page p8=FindTrialPage(trial,"/8"),p10=FindTrialPage(trial,"/10");
            Function fan=FindTrialFunction(p8,"FAN1","M2W_VE");
            Terminal fourth=null,motorPE=null;
            foreach(Function f in p10.Functions)if(f.Name.EndsWith("-X7PE:4",StringComparison.Ordinal))fourth=f as Terminal;
            foreach(Function f in FindTrialPage(trial,"/4").Functions)if(f.Name.EndsWith("-X3:4",StringComparison.Ordinal))motorPE=f as Terminal;
            if(fan==null || fourth==null || motorPE==null || fan.Pins.Length!=3 || fan.Pins[2].Potential!=Pin.PotentialType.PE)return Error("BASIC_FIX_PIN_CONFLICT","Expected installed fan PE pin");
            foreach(Connection edge in fan.Connections)if((edge.StartSymbolReference==fan && edge.StartIndex==2)||(edge.EndSymbolReference==fan && edge.EndIndex==2))return Error("BASIC_FIX_PIN_OCCUPIED","Preserve fan PE wiring");
            var motorIP=PhaseAttached(motorPE,0);
            if(!motorIP.VisibleName.EndsWith("PE_D4",StringComparison.Ordinal) || !expected.Remove(PhaseEdgeKey(fourth,1,motorPE,0)))return Error("BASIC_FIX_ROUTE_CONFLICT","Expected PE branch differs: "+motorIP.VisibleName+" / "+PhaseEdgeKey(fourth,1,motorPE,0));
            foreach(Function f in p10.Functions)if(f.Name.EndsWith("-X7PE:5",StringComparison.Ordinal))return Error("BASIC_FIX_TARGET_EXISTS","Preserve existing terminal 5");
            string original=File.ReadAllText(record,Encoding.UTF8);bool mutated=false;
            try
            {
                trial.LockAllObjects();mutated=true;
                int groupIndex=0;foreach(string tag in new[]{"X6P","X6M","X8P"})
                {foreach(TerminalStrip strip in FindTrialPage(trial,"/9").TerminalStrips)if(strip.VisibleName==tag){strip.Location=new PointD(20+groupIndex*35,175);}groupIndex++;}
                var fifth=new Terminal();fifth.Create(fourth.TerminalStrip,p10,PhaseVariant(trial,"X"));
                fifth.Properties.FUNC_PINORTERMINALNUMBER="5";fifth.VisibleName="";fifth.Location=new PointD(158,79);
                fifth.Pins[0].IsExtern=false;fifth.Pins[1].IsExtern=false;
                AttachTrialInterruption(trial,fifth,0,"PE_D4",20,false,103);
                AttachTrialInterruption(trial,fifth,1,"PE_D5",20,true,100);
                motorIP.Name="PE_D5";motorIP.VisibleName="PE_D5";motorIP.IsStarSource=false;motorIP.Properties.INTERRUPTIONPOINT_SORT_CODE=101;
                AttachTrialInterruption(trial,fan,2,"PE_D5",20,false,102);
                var fanText=new MultiLangString();fanText.AddString(ISOCode.Language.L_zh_CN,"柜内散热风扇；本图按带PE机壳绘制，PE接X7PE:5；实际型号、额定值待选型");fan.Properties.FUNC_TEXT=fanText;
                expected.Add(PhaseEdgeKey(fourth,1,fifth,0));expected.Add(PhaseEdgeKey(fifth,1,motorPE,0));expected.Add(PhaseEdgeKey(fifth,1,fan,2));
                using(var g=new Generate())g.Connections(trial,false);
                var actual=ChineseEdges(trial);if(actual.Count!=123 || !expected.SetEquals(actual))throw new InvalidOperationException("Expected exactly 123 edges after PE distribution repair");
                // Update only exact owned annotations; preserve all other user text.
                foreach(Page p in trial.Pages)foreach(Placement placement in p.AllGraphicalPlacements)
                {
                    var t=placement as DrawingText;if(t==null)continue;string old=t.Contents.GetString(ISOCode.Language.L_zh_CN);
                    string value=old.Replace("121条原生连接","123条原生连接").Replace("共49个端子位","共50个端子位").Replace("新增分配端子26位","新增分配端子27位");
                    if(old=="FAN1：柜内散热风扇；独立交流散热支路；额定值及保护接地要求待选型")value="FAN1：柜内散热风扇；本图带PE机壳经X7PE:5接地；实际型号和额定值待定";
                    if(value!=old){t.LockObject();var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,value);t.Contents=m;}
                    if(p.IdentifyingName=="/5" && old=="KM0：安全链控制接触器；位于变频器输入侧；线圈返回及反馈待闭合，不代表已验证安全停机")
                    {t.LockObject();t.Location=new PointD(25,40);}
                }
                ChineseText(p10,210,62,"X7PE:5分配至电机PE与FAN1机壳PE；实体PE端子、桥接和容量待选型",2.0);
                File.WriteAllText(Path.Combine(root,@"artifacts\three_phase_applied.before_basic_fix.json"),original,Encoding.UTF8);
                applied["expected_native_edges"]=expected;applied["native_edges"]=123;applied["basic_fix_revision"]="fan-pe-1";
                File.WriteAllText(record,serializer.Serialize(applied),Encoding.UTF8);
                var result=new Dictionary<string,object>{{"native_edges",123},{"terminal_positions",50},{"fan_pe_connected",true},{"old_edges_removed",1},{"new_edges_added",3},{"physical_pe_terminal_verified",false},{"production_release_allowed",false}};
                File.WriteAllText(marker,serializer.Serialize(result),Encoding.UTF8);return Ok(result);
            }
            catch(Exception ex)
            {
                if(mutated)File.WriteAllText(Path.Combine(root,@"artifacts\basic_fix_partial.json"),serializer.Serialize(new{error=ex.Message,expected=expected,actual=ChineseEdges(trial)}),Encoding.UTF8);
                return Error("BASIC_FIX_PARTIAL_OR_FAILED",ex.Message);
            }
        }
    }
}
