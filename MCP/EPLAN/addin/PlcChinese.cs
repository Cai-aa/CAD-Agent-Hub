using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.EObjects;
using Eplan.EplApi.HEServices;
using DrawingText = Eplan.EplApi.DataModel.Graphics.Text;

namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private const string ChinesePlanHash = "1f5e86ba1fe792a88453deaa886dbcac6e26dc7d692d05b89c53133c051b1d91";
        private static bool At(Function f, double x, double y) { return Math.Abs(f.Location.X-x)<0.001 && Math.Abs(f.Location.Y-y)<0.001; }

        private static bool ChineseLayoutActive(Project project)
        {
            Page page=FindTrialPage(project,"/6");if(page==null)return false;
            foreach(Function f in page.Functions)if(f.SymbolVariant!=null && f.SymbolVariant.SymbolName=="PLCCP" &&
                !f.Properties.FUNC_CONNECTIONDESIGNATION[1].IsEmpty && f.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString()=="DI0_TBD")return true;
            return false;
        }

        private static void ChineseHideLongFunctionText(Function f)
        {
            if(!f.UseLocalPropertyPlacements)f.SwitchLocalPropertyPlacements(true);
            foreach(var p in f.PropertyPlacements)
                if(p.DisplayedProperty==Properties.Function.FUNC_TEXT || p.DisplayedProperty==Properties.Function.FUNC_TEXT_AUTOMATIC)
                {p.LockObject();p.IsSetAsVisible=Placement.Visibility.Invisible;}
        }

        private static SortedSet<string> ChineseEdges(Project project)
        {
            var edges = new SortedSet<string>();
            foreach (Page page in project.Pages) foreach (Function f in page.Functions) foreach (Connection c in f.Connections)
            {
                string a = c.StartSymbolReference.TypeIdentifier+":"+c.StartSymbolReference.ObjectIdentifier+":"+c.StartIndex;
                string b = c.EndSymbolReference.TypeIdentifier+":"+c.EndSymbolReference.ObjectIdentifier+":"+c.EndIndex;
                edges.Add((String.CompareOrdinal(a,b)<0 ? a+"|"+b : b+"|"+a)+"|"+c.IsPlaced);
            }
            return edges;
        }

        private static Function ChineseRole(Project project, string role)
        {
            Function result=null;
            foreach (Page page in project.Pages) foreach (Function f in page.Functions)
                if (f.SymbolVariant!=null && f.SymbolVariant.SymbolName=="DCP" && f.VisibleName=="PLC1" &&
                    !f.Properties.FUNC_CONNECTIONDESIGNATION[1].IsEmpty && f.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString()==role)
                { if(result!=null)throw new InvalidOperationException("Ambiguous PLC supply role"); result=f; }
            if(result==null)throw new InvalidOperationException("Missing PLC supply role "+role);
            return result;
        }

        private static void ChineseMoveSupply(Function f, Page destination, double x, double y, string net, int sort)
        {
            // Preserve the owned interruption object, name, order and variant; only its placement changes.
            InterruptionPoint ip=null;
            foreach(Placement p in f.Page.AllPlacements)
            {
                var candidate=p as InterruptionPoint;
                if(candidate!=null && candidate.VisibleName==net && !candidate.IsStarSource &&
                    !candidate.Properties.INTERRUPTIONPOINT_SORT_CODE.IsEmpty && candidate.Properties.INTERRUPTIONPOINT_SORT_CODE.ToString()==sort.ToString())
                { if(ip!=null)throw new InvalidOperationException("Ambiguous supply interruption"); ip=candidate; }
            }
            if(ip==null || f.SymbolVariant.VariantNr!=1 || ip.SymbolVariant.VariantNr!=2)
                throw new InvalidOperationException("Unverified PLC supply geometry");
            double dx=x-f.Location.X,dy=y-f.Location.Y;
            f.Page=destination; f.Location=new PointD(x,y);
            ip.Page=destination; ip.Location=new PointD(ip.Location.X+dx,ip.Location.Y+dy);
            if(!f.UseLocalPropertyPlacements)f.SwitchLocalPropertyPlacements(true);
            foreach(var p in f.PropertyPlacements) { p.LockObject(); p.IsSetAsVisible=Placement.Visibility.Invisible; }
        }

        private static void ChineseText(Page page, double x, double y, string value, double height)
        {
            int count=0;
            foreach(Placement p in page.AllGraphicalPlacements)
            {
                var t=p as DrawingText;
                if(t!=null && t.Contents.GetString(ISOCode.Language.L_zh_CN)==value &&
                    Math.Abs(t.Location.X-x)<0.001 && Math.Abs(t.Location.Y-y)<0.001 && Math.Abs(t.Height-height)<0.001)count++;
            }
            if(count>1)throw new InvalidOperationException("Duplicate owned Chinese annotation");
            if(count==0)
            {
                var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,value);
                var t=new DrawingText();t.Create(page,m,height);t.Location=new PointD(x,y);
            }
        }

        private Dictionary<string, object> FormatTrialPlcChinese(ProjectManager pm, Project[] projects)
        {
            string root=RuntimePath(@"");
            string planPath=Path.Combine(root,@"artifacts\plc_chinese.plan.json");
            if(FileSha256(planPath)!=ChinesePlanHash)return Error("CHINESE_PLAN_HASH_MISMATCH","Plan requires a tested add-in rebuild");
            var plan=(Dictionary<string,object>)new JavaScriptSerializer().DeserializeObject(File.ReadAllText(planPath,Encoding.UTF8));
            if(Convert.ToString(plan["schema"])!="plc-chinese-1" || FileSha256(Path.Combine(root,@"artifacts\motor_forward_reverse.design.json"))!=Convert.ToString(plan["model_sha256"]))
                return Error("CHINESE_PLAN_STALE","Design identity changed");
            Project trial=null;string path=Path.Combine(root,@"workspace\motor_forward_reverse_trial.elk");
            foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;
            if(trial==null){pm.LockProjectByDefault=true;trial=pm.OpenProject(path);}
            string stage="preflight";
            try
            {
                var channels=new Terminal[16];var boxes=new PLC[2];
                Page di=FindTrialPage(trial,"/6"),dout=FindTrialPage(trial,"/7");
                if(di==null || dout==null)return Error("PAGE_NOT_FOUND","PLC pages");
                for(int k=0;k<2;k++)foreach(PLC b in (k==0?di:dout).PLCs)if(b.VisibleName=="PLC1")
                {if(boxes[k]!=null)return Error("PLC_BOX_AMBIGUOUS","PLC1");boxes[k]=b;}
                if(boxes[0]==null || boxes[1]==null)return Error("PLC_BOX_NOT_FOUND","PLC1");
                foreach(Page page in new[]{di,dout})foreach(Function f in page.Functions)
                {
                    var t=f as Terminal;
                    if(t==null || t.SymbolVariant==null || t.SymbolVariant.SymbolName!="PLCCP" || t.Properties.FUNC_PLCADDRESS.IsEmpty)continue;
                    string addr=t.Properties.FUNC_PLCADDRESS.ToString();
                    int j=-1;for(int z=0;z<16;z++)if(addr==(z<8?"I0.":"Q0.")+(z%8))j=z;
                    if(j<0 || channels[j]!=null)return Error("PLC_CHANNEL_CONFLICT",addr);
                    channels[j]=t;
                }
                double[] ix={50,100,150,200,250,290,330,370},qx={60,110,160,200,230,260,315,355};
                for(int j=0;j<16;j++)
                {
                    if(channels[j]==null)return Error("PLC_CHANNEL_MISSING",j.ToString());
                    int c=j%8;var t=channels[j];PointD old=PlcTrialLocation(j<8?j*2:c*2+1);
                    if(!At(t,old.X,old.Y) && !At(t,j<8?ix[c]:qx[c],j<8?100:55))return Error("PLC_LAYOUT_CONFLICT","Preserve unexpected placement");
                    string pin=t.Properties.FUNC_CONNECTIONDESIGNATION[1].IsEmpty?"":t.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString();
                    if(pin!="" && pin!=(j<8?"DI":"DO")+c+"_TBD")return Error("PLC_PIN_CONFLICT","Preserve physical or user pin designation");
                }
                var plus=ChineseRole(trial,"ROLE_LPLUS_TBD");var zero=ChineseRole(trial,"ROLE_M_TBD");var output=ChineseRole(trial,"ROLE_DO_LPLUS_TBD");
                if((!At(plus,340,180)&&!At(plus,30,55)&&!At(plus,60,55)) || (!At(zero,340,150)&&!At(zero,30,35)&&!At(zero,60,35)) || (!At(output,340,120)&&!At(output,30,30)&&!At(output,60,30)))
                    return Error("PLC_SUPPLY_LAYOUT_CONFLICT","Supply locations differ from known revisions");
                var x26=FindTrialTerminal(trial,"X2","6");
                if(!At(x26,280,80)&&!At(x26,390,175))return Error("TERMINAL_LAYOUT_CONFLICT","X2:6");
                var ann=(Dictionary<string,object>)plan["annotations"];
                var textChanges=new List<KeyValuePair<Function,string>>();
                foreach(Page page in trial.Pages)foreach(Function f in page.Functions)
                {
                    string tag=f.VisibleName;
                    if(!ann.ContainsKey(tag))foreach(string key in ann.Keys)
                        if(f.Name.EndsWith("-"+key,StringComparison.Ordinal) || f.Name.IndexOf("-"+key+":",StringComparison.Ordinal)>=0){tag=key;break;}
                    if(!ann.ContainsKey(tag))continue;
                    var a=(Dictionary<string,object>)ann[tag];string value=Convert.ToString(a["name"])+"；"+Convert.ToString(a["meaning"]);
                    string old=f.Properties.FUNC_TEXT.IsEmpty?"":f.Properties.FUNC_TEXT.ToString(ISOCode.Language.L_zh_CN);
                    if(old!="" && old!=value && !old.StartsWith("逻辑接口"))return Error("CHINESE_TEXT_CONFLICT",f.Name+": "+old);
                    textChanges.Add(new KeyValuePair<Function,string>(f,value));
                }
                foreach(object pp in (object[])plan["pages"])
                {
                    var p=(Dictionary<string,object>)pp;int n=Convert.ToInt32(p["number"]);Page page=FindTrialPage(trial,"/"+n);
                    if(n>=14 && page!=null && (page.Functions.Length!=0 || page.Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN)!=Convert.ToString(p["title"])))
                        return Error("CHINESE_PAGE_CONFLICT",n.ToString());
                }
                var noContacts=new Function[3];double[] noX={290,335,380};
                for(int j=0;j<3;j++)
                {
                    noContacts[j]=FindTrialFunction(dout,"KA"+(j+1),"S");
                    if(noContacts[j]==null || noContacts[j].Connections.Length!=0 || (!At(noContacts[j],50+j*50,60)&&!At(noContacts[j],noX[j],190)))
                        return Error("PLC_NO_CONTACT_CONFLICT","Preserve unexpected contact wiring or placement");
                }
                var before=ChineseEdges(trial);trial.LockAllObjects();
                stage="resize PLC boxes";
                boxes[0].SetLogicalArea(new PointD(30,25),new PointD(390,100));
                boxes[1].SetLogicalArea(new PointD(30,20),new PointD(385,55));
                stage="box property placements";
                foreach(var b in boxes){if(!b.UseLocalPropertyPlacements)b.SwitchLocalPropertyPlacements(true);foreach(var p in b.PropertyPlacements){p.LockObject();p.IsSetAsVisible=Placement.Visibility.Invisible;}}
                stage="PLC channels";
                for(int j=0;j<16;j++)
                {
                    stage="PLC channel "+j+" placement";
                    int c=j%8;var t=channels[j];t.Location=new PointD(j<8?ix[c]:qx[c],j<8?100:55);
                    stage="PLC channel "+j+" designation";
                    t.Properties.FUNC_CONNECTIONDESIGNATION[1]=(j<8?"DI":"DO")+c+"_TBD";
                    stage="PLC channel "+j+" signal";
                    var pins=t.Pins;pins[0].Signal=j<8?Pin.SignalType.DigitalInput:Pin.SignalType.DigitalOutput;
                    if(t.Pins[0].Signal!=(j<8?Pin.SignalType.DigitalInput:Pin.SignalType.DigitalOutput))throw new InvalidOperationException("Signal readback mismatch");
                }
                stage="supply role migration";
                ChineseMoveSupply(plus,di,60,55,"PLC24",101);
                ChineseMoveSupply(zero,di,60,35,"DC0",101);
                ChineseMoveSupply(output,dout,60,30,"OUTPUT24",101);
                // X2:6 must remain outside the PLC box. Move its unique owned DC0 target together.
                if(At(x26,280,80))
                {
                    InterruptionPoint ip=null;foreach(Placement p in di.AllPlacements)
                    {var t=p as InterruptionPoint;if(t!=null && t.VisibleName=="DC0" && t.Properties.INTERRUPTIONPOINT_SORT_CODE.ToString()=="103"){if(ip!=null)throw new InvalidOperationException("Ambiguous X2:6 return");ip=t;}}
                    if(ip==null)throw new InvalidOperationException("X2:6 return missing");
                    ip.Location=new PointD(ip.Location.X+110,ip.Location.Y+95);x26.Location=new PointD(390,175);
                }
                stage="Chinese function texts";
                foreach(var row in textChanges){var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,row.Value);row.Key.Properties.FUNC_TEXT=m;}
                foreach(var row in textChanges)ChineseHideLongFunctionText(row.Key);
                // Avoid inherited PLC main-function paragraphs on every channel.
                foreach(var t in channels)ChineseHideLongFunctionText(t);
                x26.VisibleName="X2";
                foreach(Placement p in di.AllGraphicalPlacements)
                {
                    var text=p as DrawingText;if(text==null)continue;
                    string contents=text.Contents.GetString(ISOCode.Language.L_zh_CN);
                    if(Math.Abs(text.Location.X-42)<0.001 &&
                        ((contents=="L+：控制器+24V供电，经FU1；实体脚号TBD" && Math.Abs(text.Location.Y-53)<0.001) ||
                         (contents=="M：直流0V参考；COM分组/隔离须按实际模块核实" && Math.Abs(text.Location.Y-33)<0.001)))
                    {text.LockObject();text.Location=new PointD(42,text.Location.Y-4);}
                }
                for(int j=0;j<3;j++)
                {
                    noContacts[j].Location=new PointD(noX[j],190);
                    ChineseText(dout,noX[j]-10,202,"KA"+(j+1)+" 常开触点",2.0);
                    ChineseText(dout,noX[j]-10,178,j==0?"至VFD正转待接":j==1?"至VFD反转待接":"至VFD复位待接",1.9);
                    FindTrialFunction(dout,"KA"+(j+1),"K").ContactImageType=Eplan.EplApi.DataModel.Graphics.ContactImage.Enums.ContactImageType.None;
                }
                stage="Chinese drawing annotations";
                foreach(object pp in (object[])plan["pages"])
                {
                    var p=(Dictionary<string,object>)pp;int n=Convert.ToInt32(p["number"]);Page page=FindTrialPage(trial,"/"+n);
                    if(page==null){var props=new PagePropertyList();props.PAGE_COUNTER=n;page=new Page();page.Create(trial,DocumentTypeManager.DocumentType.Graphics,props);var title=new MultiLangString();title.AddString(ISOCode.Language.L_zh_CN,Convert.ToString(p["title"]));page.Properties.PAGE_NOMINATIOMN=title;}
                    foreach(object cc in (object[])p["commands"])
                    {var c=(Dictionary<string,object>)cc;ChineseText(page,Convert.ToDouble(c["x"]),Convert.ToDouble(c["y"]),Convert.ToString(c["text"]),Convert.ToDouble(c["height"]));}
                }
                stage="native connection generation";
                using(var g=new Generate())g.Connections(trial,false);
                if(!before.SetEquals(ChineseEdges(trial)))return Error("PARTIAL_CONNECTIVITY_CHANGED","Do not retry; reconcile native edge set");
                foreach(var t in channels)if(t.PLC==null || t.PLC.VisibleName!="PLC1")return Error("PLC_BOX_ASSOCIATION_FAILED",t.Properties.FUNC_PLCADDRESS.ToString());
                return Ok(new Dictionary<string,object>{{"plan_sha256",ChinesePlanHash},{"channels",16},{"function_texts_zh",textChanges.Count},
                    {"native_edges_preserved",before.Count},{"native_plc_boxes",2},{"supply_roles_inside_boxes",3},{"physical_pins_verified",false},{"production_release_allowed",false}});
            }
            catch(Exception ex){return Error("PARTIAL_OR_FAILED_NATIVE_WRITE",stage+": "+ex.Message);}
        }
    }
}
