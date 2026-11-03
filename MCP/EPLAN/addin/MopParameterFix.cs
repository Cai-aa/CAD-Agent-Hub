using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using DrawingText=Eplan.EplApi.DataModel.Graphics.Text;
namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private const string MopFixPlanHash="abdba37684a2fb5074df0fb4c511a31ca48490648afcfaf71f7008789e84d892";
        private Dictionary<string,object> FixTrialMopParameters(ProjectManager pm,Project[] projects)
        {
            string planFile=Path.Combine(ReferenceRoot,@"artifacts\mop_parameter_fix.plan.json"),marker=Path.Combine(ReferenceRoot,@"artifacts\mop_parameter_fix_applied.json");
            if(FileSha256(planFile)!=MopFixPlanHash)return Error("MOP_PLAN_HASH_MISMATCH","Pinned parameter revision changed");
            var serializer=new JavaScriptSerializer();var plan=(Dictionary<string,object>)serializer.DeserializeObject(File.ReadAllText(planFile,Encoding.UTF8));
            Project trial=null;string path=Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk");foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))trial=p;if(trial==null)trial=pm.OpenProject(path);
            string reference=Path.Combine(ReferenceRoot,@"artifacts\reference_interfaces_applied.json");
            if(FileSha256(reference)!=Convert.ToString(plan["reference_manifest_sha256"]))return Error("MOP_REFERENCE_STALE","Reference manifest differs");
            var applied=(Dictionary<string,object>)serializer.DeserializeObject(File.ReadAllText(reference,Encoding.UTF8));var expected=new SortedSet<string>();foreach(object edge in (object[])applied["expected_native_edges"])expected.Add(Convert.ToString(edge));
            if(expected.Count!=151 || !expected.SetEquals(ChineseEdges(trial)))return Error("MOP_GRAPH_CONFLICT","Preserve changed electrical topology");
            bool already=File.Exists(marker);
            if(!already && FileSha256(Path.Combine(ReferenceRoot,@"artifacts\motor_forward_reverse.design.json"))!=Convert.ToString(plan["baseline_model_sha256"]))return Error("MOP_MODEL_STALE","Model changed before parameter correction");
            var changes=new Dictionary<DrawingText,string>();var missingNotes=new List<Dictionary<string,object>>();
            foreach(object item in (object[])plan["text_replacements"])
            {
                var entry=(Dictionary<string,object>)item;Page page=FindTrialPage(trial,"/"+Convert.ToInt32(entry["page"]));if(page==null)return Error("MOP_PAGE_MISSING","Missing fixed reference page");
                string old=Convert.ToString(entry["old"]),next=Convert.ToString(entry["new"]);int found=0;
                foreach(Placement placement in page.AllGraphicalPlacements){var text=placement as DrawingText;if(text==null)continue;string value=text.Contents.GetString(ISOCode.Language.L_zh_CN);if(value==old || value==next){found++;if(value==old)changes[text]=next;}}
                if(found!=1)return Error("MOP_TEXT_CONFLICT","Preserve changed or duplicate owned caption on page "+entry["page"]+": "+old);
            }
            foreach(object item in (object[])plan["notes"])
            {
                var note=(Dictionary<string,object>)item;Page page=FindTrialPage(trial,"/"+Convert.ToInt32(note["page"]));double x=Convert.ToDouble(note["x"]),y=Convert.ToDouble(note["y"]);int found=0;
                foreach(Placement placement in page.AllGraphicalPlacements){var text=placement as DrawingText;if(text==null || Math.Abs(text.Location.X-x)>0.001 || Math.Abs(text.Location.Y-y)>0.001)continue;if(text.Contents.GetString(ISOCode.Language.L_zh_CN)!=Convert.ToString(note["text"]))return Error("MOP_NOTE_CONFLICT","Preserve unrelated text at correction location");found++;}
                if(found>1)return Error("MOP_NOTE_CONFLICT","Duplicate note");if(found==0)missingNotes.Add(note);
            }
            if(already && (changes.Count>0 || missingNotes.Count>0))return Error("MOP_APPLIED_REVISION_CONFLICT","Applied reference notes were changed");
            if(already)return Ok(new{already_applied=true,parameter_revision="mop-positive-fixed-1",project_modified=false,native_edges=151});
            trial.LockAllObjects();
            foreach(var pair in changes){pair.Key.LockObject();var text=new MultiLangString();text.AddString(ISOCode.Language.L_zh_CN,pair.Value);pair.Key.Contents=text;}
            foreach(var note in missingNotes)ChineseText(FindTrialPage(trial,"/"+Convert.ToInt32(note["page"])),Convert.ToDouble(note["x"]),Convert.ToDouble(note["y"]),Convert.ToString(note["text"]),Convert.ToDouble(note["height"]));
            if(!expected.SetEquals(ChineseEdges(trial)))return Error("MOP_PARTIAL_GRAPH_CHANGED","Inspect trial before further operations");
            var result=new{parameter_revision="mop-positive-fixed-1",plan_sha256=MopFixPlanHash,captions_updated=changes.Count,notes_added=missingNotes.Count,native_edges=151,field_parameters_applied=false,production_release_allowed=false};
            File.WriteAllText(marker,serializer.Serialize(result),Encoding.UTF8);return Ok(result);
        }
    }
}
