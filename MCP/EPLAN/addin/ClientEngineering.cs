using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.MasterData;
using Eplan.EplApi.DataModel.EObjects;
using Eplan.EplApi.HEServices;
using DrawingText=Eplan.EplApi.DataModel.Graphics.Text;
using DrawingRectangle=Eplan.EplApi.DataModel.Graphics.Rectangle;
using DrawingLine=Eplan.EplApi.DataModel.Graphics.Line;
using DrawingArc=Eplan.EplApi.DataModel.Graphics.Arc;

namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private const string ClientPlanHash="905255e26189c6005788f8e1f6979c1a509f74eb91cd38f8315bd5383d78e629";
        private const string ClientFinishHash="f14901379cea61414d6564fb085842bc896fe0b77d4a6d84393806b41e20058d";

        private Dictionary<string,object> FinalizeClientDocument(ProjectManager pm,Project[] projects)
        {
            string marker=Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0_applied.json");if(!File.Exists(marker))return Error("CLIENT_REVISION_REQUIRED","Verified A0 revision required");
            var checkedState=ApplyClientEngineering(pm,projects,true);if(!(bool)checkedState["ok"])return checkedState;
            Project trial=null;foreach(Project p in pm.OpenProjects)if(String.Equals(p.ProjectLinkFilePath,Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk"),StringComparison.OrdinalIgnoreCase))trial=p;
            var titles=new Dictionary<string,string[]>{{"/18",new[]{"暂定 BOM 设计需求表 1","设计选型BOM及待确认动力项 1"}},{"/19",new[]{"暂定 BOM 设计需求表 2","设计选型BOM及待确认动力项 2"}},{"/20",new[]{"参考BOM增补与安装约束","设计选型BOM及端子附件 3"}},{"/22",new[]{"柜内二维排布方案 - 尺寸TBD","柜内二维尺寸布局与安装净距（送审）"}},{"/23",new[]{"柜门二维排布方案 - 开孔TBD","柜门孔位坐标与侧面通风（送审）"}}};
            foreach(var pair in titles){var page=FindTrialPage(trial,pair.Key);string current=page.Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN);if(current!=pair.Value[0]&&current!=pair.Value[1])return Error("CLIENT_PAGE_TITLE_CHANGED",pair.Key);}
            trial.LockAllObjects();var result=new Dictionary<string,object>();int updated=0;
            foreach(var pair in titles){var page=FindTrialPage(trial,pair.Key);if(page.Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN)!=pair.Value[1]){var value=new MultiLangString();value.AddString(ISOCode.Language.L_zh_CN,pair.Value[1]);page.Properties.PAGE_NOMINATIOMN=value;updated++;}result[pair.Key]=pair.Value[1];}
            var ser=new JavaScriptSerializer();var applied=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(marker,Encoding.UTF8));applied["page_titles"]=result;File.WriteAllText(marker,ser.Serialize(applied),Encoding.UTF8);
            return Ok(new{page_titles_updated=updated,total_native_pages=trial.Pages.Length,native_edges=ChineseEdges(trial).Count,project_modified=updated>0,production_release_allowed=false});
        }

        private Dictionary<string,object> FinishClientPartial(Project trial,Dictionary<string,object> plan,string marker,string partial)
        {
            string path=Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0_finish.plan.json");
            if(FileSha256(path)!=ClientFinishHash)return Error("CLIENT_FINISH_PLAN_HASH_MISMATCH","Only the compiled fixed partial repair is enabled");
            var ser=new JavaScriptSerializer();var fix=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(path,Encoding.UTF8));
            if(Convert.ToString(fix["parent_plan_sha256"])!=ClientPlanHash)return Error("CLIENT_FINISH_PARENT_MISMATCH","Repair belongs to another plan");
            var before=new SortedSet<string>();foreach(object e in (object[])fix["before_edges"])before.Add(Convert.ToString(e));if(!before.SetEquals(ChineseEdges(trial)))return Error("CLIENT_FINISH_GRAPH_CHANGED","Preserve graph changes since diagnosis");
            foreach(var pair in (Dictionary<string,object>)fix["before_graphics"]){var p=FindTrialPage(trial,pair.Key);if(p==null||ClientHash(ser.Serialize(ClientGraphics(p)))!=Convert.ToString(pair.Value))return Error("CLIENT_FINISH_DRAWING_CHANGED",pair.Key);}
            var added=new Dictionary<string,RefEnd>();foreach(var pair in (Dictionary<string,object>)fix["new_endpoints"]){var row=(Dictionary<string,object>)pair.Value;var f=ClientFunction(trial,Convert.ToInt64(row["object_id"]));if(f.Name!=Convert.ToString(row["name"])||f.SymbolVariant.SymbolName!=Convert.ToString(row["symbol"]))return Error("CLIENT_FINISH_ENDPOINT_CHANGED",pair.Key);added[pair.Key]=new RefEnd(f,0);}
            var link=added["X0.1"].F;if(Math.Abs(link.Location.X-350)>.001||Math.Abs(link.Location.Y-75)>.001)return Error("CLIENT_FINISH_LOCATION_CHANGED","Unexpected X0 position");
            InterruptionPoint up=null,down=null;foreach(Placement placement in link.Page.AllPlacements){var ip=placement as InterruptionPoint;if(ip==null||Math.Abs(ip.Location.X-350)>.001)continue;if(Math.Abs(ip.Location.Y-94)<.001){if(up!=null)return Error("CLIENT_FINISH_IP_AMBIGUOUS","Duplicate upper link arrow");up=ip;}if(Math.Abs(ip.Location.Y-58.25)<.001){if(down!=null)return Error("CLIENT_FINISH_IP_AMBIGUOUS","Duplicate lower link arrow");down=ip;}}
            if(up==null||down==null||up.IsStarSource||down.IsStarSource || up.VisibleName!=PhaseAttached(ClientFunction(trial,35),0).VisibleName || down.VisibleName!=PhaseAttached(ClientFunction(trial,430),0).VisibleName)return Error("CLIENT_FINISH_IP_CHANGED","Expected original M and PE link targets");
            trial.LockAllObjects();link.Location=new PointD(375,75);up.Location=new PointD(375,94);down.Location=new PointD(375,58.25);
            using(var g=new Generate())g.Connections(trial,false);
            var expected=new SortedSet<string>();foreach(object e in (object[])fix["expected_edges"])expected.Add(Convert.ToString(e));
            if(expected.Count!=161||!expected.SetEquals(ChineseEdges(trial)))return Error("CLIENT_FINISH_PARTIAL_GRAPH_MISMATCH","Inspect repaired coordinates before further writes");
            var endpoints=new Dictionary<string,object>();foreach(object obj in (object[])plan["endpoint_labels"]){var row=(Dictionary<string,object>)obj;var f=ClientFunction(trial,Convert.ToInt64(row["object_id"]));int pin=Convert.ToInt32(row["pin_index"]);endpoints[Convert.ToString(row["logical"])]=new{object_id=f.ObjectIdentifier,type_id=f.TypeIdentifier,pin_index=pin,display_designation=f.Properties.FUNC_CONNECTIONDESIGNATION[pin+1].ToString()};}
            foreach(var pair in added)endpoints[pair.Key]=new{object_id=pair.Value.F.ObjectIdentifier,type_id=pair.Value.F.TypeIdentifier,pin_index=0,display_designation=pair.Value.F.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString()};
            var postPages=new Dictionary<string,object>();var postIO=new Dictionary<string,object>();foreach(Page p in trial.Pages){postPages[p.IdentifyingName]=ClientHash(ser.Serialize(ClientGraphics(p)));foreach(Function f in p.Functions){var t=f as Terminal;if(t==null||t.SymbolVariant.SymbolName!="PLCCP")continue;string addr=t.Properties.FUNC_PLCADDRESS.ToString();if(postIO.ContainsKey(addr))throw new InvalidOperationException("Duplicate PLC address");postIO[addr]=new{object_id=t.ObjectIdentifier,page=p.IdentifyingName,label=t.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString(),signal=t.Pins[0].Signal.ToString()};}}
            if(postIO.Count!=24)throw new InvalidOperationException("Expected all 24 digital channels");
            var result=new{revision="client-engineering-A0",plan_sha256=ClientPlanHash,finish_plan_sha256=ClientFinishHash,expected_native_edges=expected,native_edges=161,pages=24,terminal_positions=59,plc_channels=24,logical_native_endpoints=endpoints,post_page_sha256=postPages,post_io=postIO,reference_bond_terminal="X0:1",field_inputs_confirmed=false,construction_release_allowed=false,production_release_allowed=false};
            File.WriteAllText(marker,ser.Serialize(result),Encoding.UTF8);File.Move(partial,Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0_partial_reconciled_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss")+".json"));return Ok(result);
        }
        private static string ClientHash(string text)
        {using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(Encoding.UTF8.GetBytes(text))).Replace("-","").ToLowerInvariant();}
        private static List<Dictionary<string,object>> ClientGraphics(Page page)
        {
            var rows=new List<Dictionary<string,object>>();
            foreach(Placement p in page.AllGraphicalPlacements)
            {
                var t=p as DrawingText;var r=p as DrawingRectangle;var l=p as DrawingLine;var a=p as DrawingArc;
                if(t==null && r==null && l==null && a==null)continue;
                var row=new Dictionary<string,object>{{"id",p.ObjectIdentifier},{"type",p.TypeIdentifier},{"x",p.Location.X},{"y",p.Location.Y}};
                if(t!=null){row["kind"]="text";row["text"]=t.Contents.GetString(ISOCode.Language.L_zh_CN);}
                if(r!=null){row["kind"]="rect";row["x1"]=r.LowerLeftCorner.X;row["y1"]=r.LowerLeftCorner.Y;row["x2"]=r.UpperRightCorner.X;row["y2"]=r.UpperRightCorner.Y;}
                if(l!=null){row["kind"]="line";row["x1"]=l.StartPoint.X;row["y1"]=l.StartPoint.Y;row["x2"]=l.EndPoint.X;row["y2"]=l.EndPoint.Y;}
                if(a!=null){row["kind"]="arc";row["radius"]=a.Radius;row["start_angle"]=a.StartAngle;row["end_angle"]=a.EndAngle;}
                rows.Add(row);
            }
            rows.Sort((a,b)=>Convert.ToInt64(a["id"]).CompareTo(Convert.ToInt64(b["id"])));return rows;
        }
        private static Function ClientFunction(Project p,long id)
        {Function found=null;foreach(Page page in p.Pages)foreach(Function f in page.Functions)if(f.ObjectIdentifier==id){if(found!=null)throw new InvalidOperationException("Ambiguous object identity");found=f;}if(found==null)throw new InvalidOperationException("Missing owned function "+id);return found;}
        private Dictionary<string,object> InspectClientEngineering(ProjectManager pm,Project[] projects)
        {
            string path=Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk");Project p=null;foreach(Project current in projects)if(String.Equals(current.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))p=current;if(p==null)p=pm.OpenProject(path);
            var pages=new List<object>();var ser=new JavaScriptSerializer();
            foreach(Page page in p.Pages){var rows=ClientGraphics(page);pages.Add(new{page=page.IdentifyingName,graphics=rows,graphics_sha256=ClientHash(ser.Serialize(rows))});}
            return Ok(new{instance_id=instanceId,project=p.ProjectLinkFilePath,model_sha256=FileSha256(Path.Combine(ReferenceRoot,@"artifacts\motor_forward_reverse.design.json")),native_edges=ChineseEdges(p),pages=pages,project_modified=false});
        }
        private static void ClientDraw(Page page,object[] primitives)
        {
            if(primitives.Length>650)throw new InvalidOperationException("Primitive count out of fixed scope");
            foreach(object obj in primitives)
            {
                var p=(Dictionary<string,object>)obj;string kind=Convert.ToString(p["kind"]);
                if(kind=="text")ChineseText(page,Convert.ToDouble(p["x"]),Convert.ToDouble(p["y"]),Convert.ToString(p["text"]),Convert.ToDouble(p["height"]));
                else if(kind=="rect"){var r=new DrawingRectangle();r.Create(page);double x=Convert.ToDouble(p["x"]),y=Convert.ToDouble(p["y"]);r.SetArea(new PointD(x,y),new PointD(x+Convert.ToDouble(p["w"]),y+Convert.ToDouble(p["h"])));if(p.ContainsKey("label")&&Convert.ToString(p["label"])!="")ChineseText(page,x+1,y+Convert.ToDouble(p["h"])-4,Convert.ToString(p["label"]),1.8);}
                else if(kind=="line"){var l=new DrawingLine();l.Create(page,new PointD(Convert.ToDouble(p["x1"]),Convert.ToDouble(p["y1"])),new PointD(Convert.ToDouble(p["x2"]),Convert.ToDouble(p["y2"])));}
                else if(kind=="circle"){var a=new DrawingArc();a.Create(page);a.SetCircle(new PointD(Convert.ToDouble(p["cx"]),Convert.ToDouble(p["cy"])),Convert.ToDouble(p["r"]));}
                else throw new InvalidOperationException("Unsupported fixed graphical primitive");
            }
        }
        private Dictionary<string,object> ApplyClientEngineering(ProjectManager pm,Project[] projects,bool reconcile)
        {
            string planFile=Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0.plan.json"),marker=Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0_applied.json"),partial=Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0_partial.json");
            if(FileSha256(planFile)!=ClientPlanHash)return Error("CLIENT_PLAN_HASH_MISMATCH","Client drawing plan is not the compiled immutable revision");
            var ser=new JavaScriptSerializer();var plan=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(planFile,Encoding.UTF8));
            if(Convert.ToString(plan["schema"])!="client-engineering-plan-1")return Error("CLIENT_SCHEMA_MISMATCH","Unexpected plan schema");
            string path=Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk");Project trial=null;foreach(Project current in projects)if(String.Equals(current.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=current;if(trial==null)trial=pm.OpenProject(path);
            if(File.Exists(marker))
            {
                var applied=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(marker,Encoding.UTF8));var edges=new SortedSet<string>();foreach(object e in (object[])applied["expected_native_edges"])edges.Add(Convert.ToString(e));
                if(Convert.ToString(applied["plan_sha256"])!=ClientPlanHash)return Error("CLIENT_MARKER_PLAN_MISMATCH","Marker belongs to another compiled plan");
                if(!edges.SetEquals(ChineseEdges(trial)))return Error("CLIENT_APPLIED_GRAPH_CHANGED","Preserve changed client circuit");
                foreach(object obj in (object[])plan["function_labels"]){var row=(Dictionary<string,object>)obj;var f=ClientFunction(trial,Convert.ToInt64(row["object_id"]));var labels=(object[])row["new_labels"];for(int i=0;i<labels.Length;i++)if(f.Properties.FUNC_CONNECTIONDESIGNATION[i+1].ToString()!=Convert.ToString(labels[i]))return Error("CLIENT_APPLIED_LABEL_CHANGED","A physical terminal was edited after apply");}
                foreach(var pair in (Dictionary<string,object>)applied["logical_native_endpoints"]){var row=(Dictionary<string,object>)pair.Value;var f=ClientFunction(trial,Convert.ToInt64(row["object_id"]));if(f.TypeIdentifier!=Convert.ToInt32(row["type_id"]) || f.Properties.FUNC_CONNECTIONDESIGNATION[Convert.ToInt32(row["pin_index"])+1].ToString()!=Convert.ToString(row["display_designation"]))return Error("CLIENT_NEW_ENDPOINT_CHANGED",pair.Key);}
                foreach(var pair in (Dictionary<string,object>)applied["post_page_sha256"]){var p=FindTrialPage(trial,pair.Key);if(p==null || ClientHash(ser.Serialize(ClientGraphics(p)))!=Convert.ToString(pair.Value))return Error("CLIENT_DRAWING_CHANGED",pair.Key);}
                if(applied.ContainsKey("page_titles"))foreach(var pair in (Dictionary<string,object>)applied["page_titles"])if(FindTrialPage(trial,pair.Key).Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN)!=Convert.ToString(pair.Value))return Error("CLIENT_PAGE_TITLE_CHANGED",pair.Key);
                var io=new Dictionary<string,object>();foreach(Page p in trial.Pages)foreach(Function f in p.Functions){var t=f as Terminal;if(t==null||t.SymbolVariant.SymbolName!="PLCCP")continue;string addr=t.Properties.FUNC_PLCADDRESS.ToString();if(io.ContainsKey(addr))return Error("CLIENT_IO_ADDRESS_DUPLICATED",addr);io[addr]=new{object_id=t.ObjectIdentifier,page=p.IdentifyingName,label=t.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString(),signal=t.Pins[0].Signal.ToString()};}
                var previousIO=(Dictionary<string,object>)applied["post_io"];if(io.Count!=previousIO.Count)return Error("CLIENT_IO_CHANGED","Digital channel count changed");
                foreach(var pair in previousIO){if(!io.ContainsKey(pair.Key))return Error("CLIENT_IO_CHANGED",pair.Key);var current=(Dictionary<string,object>)ser.DeserializeObject(ser.Serialize(io[pair.Key]));var old=(Dictionary<string,object>)pair.Value;foreach(string key in new[]{"object_id","page","label","signal"})if(Convert.ToString(current[key])!=Convert.ToString(old[key]))return Error("CLIENT_IO_CHANGED",pair.Key+":"+key);}
                return Ok(new{already_applied=true,reconciled=true,project_modified=false,native_edges=edges.Count,production_release_allowed=false});
            }
            if(reconcile && File.Exists(partial))
            {
                var failed=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(partial,Encoding.UTF8));
                if(Convert.ToString(failed["stage"])=="generate and verify all native routes")return FinishClientPartial(trial,plan,marker,partial);
                if(Convert.ToString(failed["stage"])!="physical connector labels" || FindTrialPage(trial,"/24")!=null)return Error("CLIENT_PARTIAL_MANUAL_INSPECTION_REQUIRED","Recovery is limited to the known label-only stage");
                var original=new SortedSet<string>();foreach(object e in (object[])plan["baseline_edges"])original.Add(Convert.ToString(e));
                if(!original.SetEquals(ChineseEdges(trial)))return Error("CLIENT_RECOVERY_GRAPH_CHANGED","Label recovery must not touch changed topology");
                foreach(object obj in (object[])plan["caption_replacements"]){var row=(Dictionary<string,object>)obj;bool found=false;foreach(Placement placement in FindTrialPage(trial,"/"+Convert.ToInt32(row["page"])).AllGraphicalPlacements){var t=placement as DrawingText;if(t!=null && t.ObjectIdentifier==Convert.ToInt64(row["id"]) && t.Contents.GetString(ISOCode.Language.L_zh_CN)==Convert.ToString(row["old"]))found=true;}if(!found)return Error("CLIENT_RECOVERY_TEXT_CHANGED","Preserve edited or partially changed captions");}
                foreach(object obj in (object[])plan["function_labels"]){var row=(Dictionary<string,object>)obj;var f=ClientFunction(trial,Convert.ToInt64(row["object_id"]));var ls=(object[])row["new_labels"];for(int i=0;i<ls.Length;i++)if(f.Properties.FUNC_CONNECTIONDESIGNATION[i+1].ToString()!=Convert.ToString(ls[i]))return Error("CLIENT_RECOVERY_LABEL_CONFLICT","Preserve unexpected labels");}
                trial.LockAllObjects();int restored=0;foreach(object obj in (object[])plan["function_labels"]){var row=(Dictionary<string,object>)obj;var f=ClientFunction(trial,Convert.ToInt64(row["object_id"]));var ls=(object[])row["old_labels"];for(int i=0;i<ls.Length;i++)f.Properties.FUNC_CONNECTIONDESIGNATION[i+1]=Convert.ToString(ls[i]);restored++;}
                string recovered=Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0_label_recovery_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss")+".json");File.Move(partial,recovered);
                return Ok(new{recovered_known_label_only_stage=true,restored_functions=restored,native_edges=original.Count,whole_project_rollback_claimed=false,production_release_allowed=false});
            }
            if(reconcile)return Error("CLIENT_NOT_APPLIED","Reconciliation cannot apply a new plan");
            if(File.Exists(partial))return Error("CLIENT_PARTIAL_REQUIRES_INSPECTION","Inspect partial state before retry");
            if(FileSha256(Path.Combine(ReferenceRoot,@"artifacts\motor_forward_reverse.design.json"))!=Convert.ToString(plan["baseline_model_sha256"]))return Error("CLIENT_MODEL_STALE","Baseline model differs");
            var expected=new SortedSet<string>();foreach(object e in (object[])plan["baseline_edges"])expected.Add(Convert.ToString(e));
            if(expected.Count!=151 || !expected.SetEquals(ChineseEdges(trial)))return Error("CLIENT_GRAPH_CONFLICT","Preserve changed native baseline");
            if(FindTrialPage(trial,"/24")!=null)return Error("CLIENT_PAGE_CONFLICT","Preserve existing page24");
            var replacements=new Dictionary<DrawingText,string>();
            foreach(object obj in (object[])plan["caption_replacements"])
            {
                var row=(Dictionary<string,object>)obj;var page=FindTrialPage(trial,"/"+Convert.ToString(row["page"]));DrawingText found=null;
                foreach(Placement p in page.AllGraphicalPlacements)if(p.ObjectIdentifier==Convert.ToInt64(row["id"]))found=p as DrawingText;
                if(found==null || found.Contents.GetString(ISOCode.Language.L_zh_CN)!=Convert.ToString(row["old"]))return Error("CLIENT_CAPTION_CONFLICT","Preserve edited caption");replacements[found]=Convert.ToString(row["new"]);
            }
            var functions=new Dictionary<long,Function>();
            foreach(object obj in (object[])plan["function_labels"])
            {
                var row=(Dictionary<string,object>)obj;long id=Convert.ToInt64(row["object_id"]);var f=ClientFunction(trial,id);functions[id]=f;
                if(f.TypeIdentifier!=Convert.ToInt32(row["type_id"]) || f.SymbolVariant.SymbolName!=Convert.ToString(row["symbol"]) || Math.Abs(f.Location.X-Convert.ToDouble(row["x"]))>.001 || Math.Abs(f.Location.Y-Convert.ToDouble(row["y"]))>.001)return Error("CLIENT_FUNCTION_IDENTITY_CONFLICT","Function identity or location changed");
                var labels=(object[])row["old_labels"];for(int i=0;i<labels.Length;i++)if(f.Properties.FUNC_CONNECTIONDESIGNATION[i+1].ToString()!=Convert.ToString(labels[i]))return Error("CLIENT_PIN_LABEL_CONFLICT","Preserve edited physical labels");
            }
            var doorSwitch=FindTrialFunction(FindTrialPage(trial,"/10"),"SQ1","SSM");if(doorSwitch==null)return Error("CLIENT_DOOR_SWITCH_MISSING","Expected owned mechanical door switch");
            var ncSymbol=new Symbol(new SymbolLibrary(trial,"GB_symbol"),"SOM");string ncDesc=ncSymbol.Properties.SYMB_DESC.ToString();
            if(ncDesc.IndexOf("NC",StringComparison.OrdinalIgnoreCase)<0 && ncDesc.IndexOf("break",StringComparison.OrdinalIgnoreCase)<0)return Error("CLIENT_NC_SYMBOL_NOT_VERIFIED",ncDesc);
            var ncVariant=new SymbolVariant();ncVariant.Initialize(ncSymbol,0);if(ncVariant.ConnectionPoints.Length!=2)return Error("CLIENT_NC_PIN_GEOMETRY","Expected two-pin NC door switch");
            foreach(object obj in (object[])plan["graphics_pages"])
            {
                var row=(Dictionary<string,object>)obj;int page=Convert.ToInt32(row["page"]);if(page!=18&&page!=19&&page!=20&&page!=22&&page!=23)return Error("CLIENT_GRAPHICS_PAGE_DISABLED","Only owned BOM and layout pages may be redrawn");
                var p=FindTrialPage(trial,"/"+page);if(p==null||p.Functions.Length!=0||ClientHash(ser.Serialize(ClientGraphics(p)))!=Convert.ToString(row["before_sha256"]))return Error("CLIENT_GRAPHICS_STALE","Preserve edited layout or BOM page");
            }
            // Capture the existing branch nets before changing labels. All nine additions are
            // explicit fixed circuit changes, not arbitrary endpoint pairs from the client.
            var cpuM=ClientFunction(trial,424);var hl3=ClientFunction(trial,105);var doorPE=ClientFunction(trial,435);var ka3=ClientFunction(trial,35);var vfdPE=ClientFunction(trial,430);
            string m8=PhaseAttached(cpuM,0).VisibleName,m2=PhaseAttached(hl3,0).VisibleName,pe2=PhaseAttached(doorPE,0).VisibleName;
            string m7=PhaseAttached(ka3,0).VisibleName,pe4=PhaseAttached(vfdPE,0).VisibleName;
            string n2=PhaseAttached(ClientFunction(trial,100),2).VisibleName;
            string stage="preflight";bool mutated=false;
            try
            {
                trial.LockAllObjects();mutated=true;stage="physical connector labels";
                foreach(object obj in (object[])plan["function_labels"]){var row=(Dictionary<string,object>)obj;var f=functions[Convert.ToInt64(row["object_id"])];var labels=(object[])row["new_labels"];for(int i=0;i<labels.Length;i++)f.Properties.FUNC_CONNECTIONDESIGNATION[i+1]=Convert.ToString(labels[i]);ChineseHideLongFunctionText(f);}
                // SQ1 is connected by direct same-page auto-connects, not by
                // interruption points. Preserve the two graphical pin positions.
                foreach(PinBase oldPin in doorSwitch.GraphicalConnectionPoints){bool same=false;foreach(PinBase nextPin in ncVariant.ConnectionPoints)if(nextPin.Index==oldPin.Index && Math.Abs(nextPin.Location.X-oldPin.Location.X)<.001 && Math.Abs(nextPin.Location.Y-oldPin.Location.Y)<.001)same=true;if(!same)throw new InvalidOperationException("NC door switch geometry differs");}
                doorSwitch.SetSymbolVariant(ncVariant,true);RefLabel(doorSwitch,"21","22");
                var text=new MultiLangString();text.AddString(ISOCode.Language.L_zh_CN,"西门子S7-1200 CPU1214C DC/DC/DC，6ES7214-1AG40-0XB0；设计选定，14DI/10DO/2AI，同一CPU分布表示");
                foreach(Page p in trial.Pages)foreach(Function f in p.Functions)if(f.VisibleName=="PLC1"){f.Properties.FUNC_TEXT=text;ChineseHideLongFunctionText(f);}
                foreach(var pair in replacements){var value=new MultiLangString();value.AddString(ISOCode.Language.L_zh_CN,pair.Value);pair.Key.Contents=value;}
                stage="native PLC spare channels and commons";
                var extra=PhasePage(trial,24,"CPU1214C备用点、公共端及单点功能接地");
                var box=new PLC();var vb=new SymbolVariant();vb.Initialize(new Symbol(new SymbolLibrary(trial,"SPECIAL"),"PLCC"),0);box.Create(extra,vb);box.Name="PLC1";box.VisibleName="PLC1";box.IsMainFunction=false;box.SetLogicalArea(new PointD(30,35),new PointD(390,230));
                if(!box.UseLocalPropertyPlacements)box.SwitchLocalPropertyPlacements(true);foreach(var pp in box.PropertyPlacements){pp.LockObject();pp.IsSetAsVisible=Placement.Visibility.Invisible;}
                var vt=new SymbolVariant();vt.Initialize(new Symbol(new SymbolLibrary(trial,"SPECIAL"),"PLCCP"),0);
                for(int i=0;i<8;i++){var t=new Terminal();t.Create(box,vt);t.Name="PLC1";t.VisibleName="PLC1";t.Page=extra;t.Location=new PointD(55+i*43,230);t.Properties.FUNC_PLCADDRESS=(i<6?"I1.":"Q1.")+(i<6?i:i-6);t.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL=(i<6?"SPARE_DI_":"SPARE_DO_")+i;t.Properties.FUNC_CONNECTIONDESIGNATION[1]=(i<6?"X10:":"X12:")+(i<6?15+i:11+i-6);t.Pins[0].Signal=i<6?Pin.SignalType.DigitalInput:Pin.SignalType.DigitalOutput;ChineseHideLongFunctionText(t);ChineseText(extra,48+i*43,216,i<6?"备用输入":"备用输出",2.0);}
                var added=new Dictionary<string,RefEnd>();
                string[] names={"DI_COMMON","DO_M","FE","AI_M","AI0","AI1","SENSOR_M"};string[] labels2={"X10:6","X12:2","X10:3","X11:1","X11:2","X11:3","X10:5"};double[] xs={70,175,280,70,175,280,350},ys={170,170,170,110,110,110,60};
                for(int i=0;i<names.Length;i++){var f=EnsureTrialRolePoint(trial,extra,"PLC1",labels2[i],0,xs[i],ys[i]);ChineseHideLongFunctionText(f);added["PLC1."+names[i]]=new RefEnd(f,0);ChineseText(extra,xs[i]+3,ys[i]-7,new[]{"1M 输入公共端","3M 输出公共端","FE 功能接地","2M 模拟量公共端","AI0 未用短接","AI1 未用短接","传感器M：接公共0V"}[i],2.0);}
                var sensorPlus=EnsureTrialRolePoint(trial,extra,"PLC1","X10:4",0,225,60);ChineseHideLongFunctionText(sensorPlus);ChineseText(extra,228,53,"传感器L+输出不用，绝缘封端",2.0);
                // The source terminals receive rated multi-conductor blocks: QUATTRO,
                // four field clamps. Bridge sockets are documented separately.
                // This two-point schematic symbol aggregates four physical field clamps
                // and one independent bridge socket at pin1. Capacity is checked again
                // as field wires versus bridge accessories in the delivery collector.
                ClientFunction(trial,473).Pins[1].MaxConnectionCount=5;
                ClientFunction(trial,467).Pins[1].MaxConnectionCount=5;
                foreach(long id in new long[]{472,477,479,459})ClientFunction(trial,id).Pins[1].MaxConnectionCount=3;
                string[] m8roles={"DI_COMMON","DO_M","SENSOR_M"};for(int i=0;i<m8roles.Length;i++){var a=added["PLC1."+m8roles[i]];AttachTrialInterruption(trial,a.F,0,m8,16,false,110+i);expected.Add(PhaseEdgeKey(ClientFunction(trial,473),1,a.F,0));}
                string[] m2roles={"AI_M","AI0","AI1"};for(int i=0;i<m2roles.Length;i++){var a=added["PLC1."+m2roles[i]];AttachTrialInterruption(trial,a.F,0,m2,16,false,110+i);expected.Add(PhaseEdgeKey(ClientFunction(trial,467),1,a.F,0));}
                AttachTrialInterruption(trial,added["PLC1.FE"].F,0,pe2,16,false,110);expected.Add(PhaseEdgeKey(ClientFunction(trial,477),1,added["PLC1.FE"].F,0));
                stage="single removable M-PE reference link";
                var strip=RefStrip(trial,extra,"X0",345,35);var link=RefTerminal(trial,strip,extra,1,350,75);added["X0.1"]=new RefEnd(link,0);
                AttachTrialInterruption(trial,link,0,m7,17,false,110);AttachTrialInterruption(trial,link,1,pe4,16,false,110);
                expected.Add(PhaseEdgeKey(ClientFunction(trial,472),1,link,0));expected.Add(PhaseEdgeKey(ClientFunction(trial,479),1,link,1));
                ChineseText(extra,200,35,"X0:1贯通端子；只允许断电拆指定0V线测量，测后恢复。",2.0);
                stage="thermostat thermal feedback neutral";
                var thermalNeutral=EnsureTrialRolePoint(trial,FindTrialPage(trial,"/10"),"TS1","6",0,320,175);ChineseHideLongFunctionText(thermalNeutral);
                added["TS1.N"]=new RefEnd(thermalNeutral,0);AttachTrialInterruption(trial,thermalNeutral,0,n2,16,false,110);expected.Add(PhaseEdgeKey(ClientFunction(trial,459),1,thermalNeutral,0));
                ChineseText(FindTrialPage(trial,"/10"),275,163,"SK3110：5-4制冷；230V热反馈N接6，7不用。",2.0);
                stage="owned BOM and mechanical drawings";
                foreach(object obj in (object[])plan["graphics_pages"]){var row=(Dictionary<string,object>)obj;var p=FindTrialPage(trial,"/"+Convert.ToInt32(row["page"]));var remove=new List<Placement>();foreach(Placement placement in p.AllGraphicalPlacements)if(placement is DrawingText||placement is DrawingRectangle||placement is DrawingLine||placement is DrawingArc)remove.Add(placement);foreach(var placement in remove)placement.Remove();ClientDraw(p,(object[])row["primitives"]);}
                foreach(object obj in (object[])plan["notes"]){var row=(Dictionary<string,object>)obj;ChineseText(FindTrialPage(trial,"/"+Convert.ToInt32(row["page"])),Convert.ToDouble(row["x"]),Convert.ToDouble(row["y"]),Convert.ToString(row["text"]),Convert.ToDouble(row["height"]));}
                stage="generate and verify all native routes";using(var g=new Generate())g.Connections(trial,false);
                if(expected.Count!=161 || !expected.SetEquals(ChineseEdges(trial)))throw new InvalidOperationException("New graph differs from all 161 pinned routes");
                var endpoints=new Dictionary<string,object>();
                foreach(object obj in (object[])plan["endpoint_labels"]){var row=(Dictionary<string,object>)obj;var f=ClientFunction(trial,Convert.ToInt64(row["object_id"]));int pin=Convert.ToInt32(row["pin_index"]);endpoints[Convert.ToString(row["logical"])]=new{object_id=f.ObjectIdentifier,type_id=f.TypeIdentifier,pin_index=pin,display_designation=f.Properties.FUNC_CONNECTIONDESIGNATION[pin+1].ToString()};}
                foreach(var pair in added)endpoints[pair.Key]=new{object_id=pair.Value.F.ObjectIdentifier,type_id=pair.Value.F.TypeIdentifier,pin_index=pair.Value.Pin,display_designation=pair.Value.F.Properties.FUNC_CONNECTIONDESIGNATION[pair.Value.Pin+1].ToString()};
                var postPages=new Dictionary<string,object>();var postIO=new Dictionary<string,object>();foreach(Page p in trial.Pages){postPages[p.IdentifyingName]=ClientHash(ser.Serialize(ClientGraphics(p)));foreach(Function f in p.Functions){var t=f as Terminal;if(t==null||t.SymbolVariant.SymbolName!="PLCCP")continue;string addr=t.Properties.FUNC_PLCADDRESS.ToString();if(postIO.ContainsKey(addr))throw new InvalidOperationException("Duplicate PLC address");postIO[addr]=new{object_id=t.ObjectIdentifier,page=p.IdentifyingName,label=t.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString(),signal=t.Pins[0].Signal.ToString()};}}
                if(postIO.Count!=24)throw new InvalidOperationException("Expected all 24 digital channels");
                var result=new{revision="client-engineering-A0",plan_sha256=ClientPlanHash,expected_native_edges=expected,native_edges=161,pages=24,terminal_positions=59,plc_channels=24,logical_native_endpoints=endpoints,post_page_sha256=postPages,post_io=postIO,reference_bond_terminal="X0:1",field_inputs_confirmed=false,construction_release_allowed=false,production_release_allowed=false};
                File.WriteAllText(marker,ser.Serialize(result),Encoding.UTF8);return Ok(result);
            }
            catch(Exception ex){if(mutated)File.WriteAllText(partial,ser.Serialize(new{stage=stage,error=ex.Message,state="PARTIAL_UNKNOWN_RECONCILE_BEFORE_RETRY",production_release_allowed=false}),Encoding.UTF8);return Error("CLIENT_PARTIAL_OR_FAILED_WRITE",stage+": "+ex.Message);}
        }
    }
}
