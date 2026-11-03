using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.HEServices;
using DrawingText=Eplan.EplApi.DataModel.Graphics.Text;

namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private Dictionary<string,object> ReviewTrialLogic(ProjectManager pm,Project[] projects)
        {
            string root=RuntimePath(@"");
            string path=Path.Combine(root,@"workspace\motor_forward_reverse_trial.elk");
            Project trial=null;foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;
            if(trial==null)trial=pm.OpenProject(path);
            if(!File.Exists(Path.Combine(root,@"artifacts\three_phase_page_order.json")))return Error("LOGIC_REVIEW_REVISION_REQUIRED","Finalized three-phase revision required");
            var applied=(Dictionary<string,object>)new JavaScriptSerializer().DeserializeObject(File.ReadAllText(Path.Combine(root,@"artifacts\three_phase_applied.json"),Encoding.UTF8));
            var expected=new SortedSet<string>();foreach(object s in (object[])applied["expected_native_edges"])expected.Add(Convert.ToString(s));
            if(expected.Count!=Convert.ToInt32(applied["native_edges"]) || !expected.SetEquals(ChineseEdges(trial)))return Error("LOGIC_REVIEW_GRAPH_CONFLICT","Preserve changed circuit");
            Page page=FindTrialPage(trial,"/16");if(page==null || !page.Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN).Contains("三相改版"))return Error("LOGIC_REVIEW_PAGE_CONFLICT","Fixed page missing");
            string[] lines={"2026-10-22 逻辑复核补充（设计规则，未部署PLC程序）",
                "统一状态：STOP_UNVERIFIED→IDLE_DISARMED→IDLE_ARMED→FORWARD或REVERSE。",
                "上电、停止、双向请求、换向或故障恢复：撤销双向命令、清除待启动及旧停稳许可。",
                "运行中READY丢失：撤销双向命令并回到待确认；READY恢复本身不得触发启动。",
                "当前停稳与等待均验证、停止链正常后，先释放两启动按钮，再接受新的单向上升沿。",
                "优先级：急停/安全丢失→故障→普通停止→READY丢失→双向冲突→恢复/换向→启动。",
                "普通停止的减速效果取决于VFD命令制式及参数；命令撤销不保证已停稳。",
                "复位是独立脉冲子逻辑：已有故障可保持、READY可低；禁止运行命令，按住不重发。",
                "复位脉宽/接口未验证、普通停止或安全异常时Q0.2=0；故障清除后仍需重新启动。",
                "本图基本控制链尚未闭合：13条安全/VFD接口未接；厂家定义确认前不能直接补线。"};
            var missing=new List<int>();
            var moves=new Dictionary<DrawingText,int>();
            for(int i=0;i<lines.Length;i++)
            {
                int matches=0;double y=95-i*7;
                foreach(Placement p in page.AllGraphicalPlacements){var t=p as DrawingText;if(t==null)continue;
                    bool old=Math.Abs(t.Location.X-25)<0.001 && Math.Abs(t.Location.Y-y)<0.001;
                    bool current=Math.Abs(t.Location.X-235)<0.001 && Math.Abs(t.Location.Y-(255-i*14))<0.001;
                    if(!old && !current)continue;
                    string value=t.Contents.GetString(ISOCode.Language.L_zh_CN);
                    if(value!=lines[i] && !(i==7 && value=="复位仅发已验证宽度的单次脉冲，按住不重触发；停机/安全异常时复位输出撤销。"))return Error("LOGIC_REVIEW_TEXT_CONFLICT","Preserve user text at fixed review location");
                    matches++;if(old || value!=lines[i])moves.Add(t,i);}
                if(matches>1)return Error("LOGIC_REVIEW_TEXT_CONFLICT","Duplicate review text");if(matches==0)missing.Add(i);
            }
            trial.LockAllObjects();foreach(var move in moves){move.Key.LockObject();move.Key.Location=new PointD(235,255-move.Value*14);var text=new MultiLangString();text.AddString(ISOCode.Language.L_zh_CN,lines[move.Value]);move.Key.Contents=text;}
            foreach(Placement p in FindTrialPage(trial,"/8").AllGraphicalPlacements)
            {var t=p as DrawingText;if(t!=null && t.Contents.GetString(ISOCode.Language.L_zh_CN)=="FAN1：柜内散热风扇；本图带PE机壳经X7PE:5接地；实际型号和额定值待定")
                {t.LockObject();t.Location=new PointD(230,250);}}
            foreach(int i in missing)ChineseText(page,235,255-i*14,lines[i],2.0);
            if(!expected.SetEquals(ChineseEdges(trial)))return Error("LOGIC_REVIEW_PARTIAL_GRAPH_CHANGED","Inspect trial before retry");
            return Ok(new Dictionary<string,object>{{"annotations_added",missing.Count},{"native_edges",expected.Count},{"electrical_topology_changed",false},{"production_release_allowed",false}});
        }
        private Dictionary<string,object> FinalizeTrialPageOrder(ProjectManager pm,Project[] projects)
        {
            string root=RuntimePath(@"");
            string path=Path.Combine(root,@"workspace\motor_forward_reverse_trial.elk");
            Project trial=null;foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;
            if(trial==null)trial=pm.OpenProject(path);
            string marker=Path.Combine(root,@"artifacts\three_phase_page_order.json");
            if(File.Exists(marker))return Ok(new Dictionary<string,object>{{"already_finalized",true},{"project_modified",false}});
            try
            {
                int[] oldNumbers={16,17,14,15,10,11,18,12,13},newNumbers={10,11,12,13,14,15,16,17,18};
                string[] titles={"三相配电","直流及按钮","关键元器件","PLC地址","BOM","BOM","三相改版","柜内","柜门"};
                var pages=new Page[oldNumbers.Length];
                for(int i=0;i<oldNumbers.Length;i++)
                {
                    pages[i]=FindTrialPage(trial,"/"+oldNumbers[i]);
                    if(pages[i]==null || FindTrialPage(trial,"/"+(110+i))!=null || !pages[i].Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN).Contains(titles[i]))
                        return Error("PAGE_ORDER_CONFLICT","Page title/counter differs from fixed revision");
                }
                var directory=new List<DrawingText>();double[] ys={211,203,195,187,179,171,163,155,147,139,131,120,111};
                foreach(Placement placement in FindTrialPage(trial,"/1").AllGraphicalPlacements)
                {
                    var t=placement as DrawingText;if(t==null || Math.Abs(t.Location.X-25)>0.001)continue;
                    bool position=false;foreach(double y in ys)if(Math.Abs(t.Location.Y-y)<0.001)position=true;
                    if(!position)continue;
                    string value=t.Contents.GetString(ISOCode.Language.L_zh_CN);int n;
                    string prefix=value.Split(' ')[0];
                    if(prefix=="10-11" || (Int32.TryParse(prefix,out n) && n>=2 && n<=15))directory.Add(t);
                }
                if(directory.Count!=13)return Error("PAGE_ORDER_DIRECTORY_CONFLICT","Preserve modified cover directory");
                var before=ChineseEdges(trial);if(before.Count!=121)return Error("PAGE_ORDER_GRAPH_CONFLICT","Expected verified 121-edge circuit");
                trial.LockAllObjects();
                // Temporary counters avoid any duplicate page identities. SetName is
                // the documented validated API; direct PAGE_COUNTER writes are read-only.
                for(int i=0;i<pages.Length;i++){var props=new PagePropertyList();props.PAGE_COUNTER=110+i;pages[i].SetName(props);}
                for(int i=0;i<pages.Length;i++){var props=new PagePropertyList();props.PAGE_COUNTER=newNumbers[i];pages[i].SetName(props);}
                foreach(Page page in trial.Pages)foreach(Placement placement in page.AllGraphicalPlacements)
                {
                    var t=placement as DrawingText;if(t==null)continue;
                    string old=t.Contents.GetString(ISOCode.Language.L_zh_CN);
                    string value=old.Replace("16-18页","10-11、16页").Replace("16/17页","10/11页").Replace("详见18页","详见16页").Replace("详见18变更表","详见16变更表");
                    if(value!=old){t.LockObject();var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,value);t.Contents=m;}
                }
                foreach(var t in directory)t.Remove();
                string[] names={"三相原电源输入与配电（电压TBD）","DC24V控制电源","三相变频器与电机动力","急停与安全链",
                    "PLC输入及电源","PLC输出与方向互锁","风扇与柜内照明","端子与外部接线","交流及PE分配端子","直流及按钮电源分配端子",
                    "关键元器件中文释义","PLC地址、信号及端子对照","暂定BOM设计需求表1","暂定BOM设计需求表2","三相改版物料增补与验收边界",
                    "柜内二维排布方案（尺寸TBD）","柜门二维排布方案（尺寸TBD）"};
                for(int i=0;i<names.Length;i++)ChineseText(FindTrialPage(trial,"/1"),25,211-i*6.1,(i+2)+"  "+names[i],2.0);
                using(var g=new Generate())g.Connections(trial,false);
                if(!before.SetEquals(ChineseEdges(trial)))return Error("PAGE_ORDER_PARTIAL_GRAPH_CHANGED","Reconcile page rename before further writes");
                var map=new Dictionary<string,int>();for(int i=0;i<pages.Length;i++)map.Add(oldNumbers[i].ToString(),newNumbers[i]);
                var result=new Dictionary<string,object>{{"page_map",map},{"pages",18},{"native_edges_preserved",121},{"layout_pages",new[]{17,18}},{"production_release_allowed",false}};
                File.WriteAllText(marker,new JavaScriptSerializer().Serialize(result),Encoding.UTF8);return Ok(result);
            }
            catch(Exception ex){return Error("PAGE_ORDER_PARTIAL_OR_FAILED",ex.Message);}
        }
    }
}
