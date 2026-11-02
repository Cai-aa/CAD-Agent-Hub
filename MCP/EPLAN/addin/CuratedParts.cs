using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.EObjects;

namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private const string CuratedPartsPlanHash="75182f621b6a3c223c3b96bb36e55cdec0c4ad665aed9e161162d552cfc1b947";
        private const string CuratedDocPlanHash="d0f0a4a7ecd752908ced88961c169a1a8648a9f9fd07e00e069a217f56b05ce5";
        private Dictionary<string,object> FinalizeCuratedDocument(ProjectManager pm,Project[] projects)
        {
            string path=Path.Combine(ReferenceRoot,@"artifacts\parts_caption_A1.plan.json"),marker=Path.Combine(ReferenceRoot,@"artifacts\parts_caption_A1_applied.json");
            if(FileSha256(path)!=CuratedDocPlanHash)return Error("PARTS_CAPTION_PLAN_HASH_MISMATCH","Pinned document correction differs");
            var ser=new JavaScriptSerializer();var plan=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(path,Encoding.UTF8));
            if(Convert.ToString(plan["schema"])!="parts-caption-plan-1"||Convert.ToString(plan["parent_parts_plan_sha256"])!=CuratedPartsPlanHash)return Error("PARTS_CAPTION_SCHEMA_MISMATCH","Known part revision required");
            var state=ApplyCuratedParts(pm,projects,true);if(!(bool)state["ok"])return state;
            var trial=CuratedTrial(pm,pm.OpenProjects);var changes=new Dictionary<Eplan.EplApi.DataModel.Graphics.Text,string>();
            foreach(object obj in (object[])plan["captions"]){var row=(Dictionary<string,object>)obj;var page=FindTrialPage(trial,Convert.ToString(row["page"]));Eplan.EplApi.DataModel.Graphics.Text found=null;foreach(Placement p in page.AllGraphicalPlacements)if(p.ObjectIdentifier==Convert.ToInt64(row["id"]))found=p as Eplan.EplApi.DataModel.Graphics.Text;if(found==null)return Error("PARTS_CAPTION_MISSING","Owned annotation missing");string value=found.Contents.GetString(ISOCode.Language.L_zh_CN);if(value!=Convert.ToString(row["old"])&&value!=Convert.ToString(row["new"]))return Error("PARTS_CAPTION_CHANGED","Preserve changed annotations");if(value!=Convert.ToString(row["new"]))changes[found]=Convert.ToString(row["new"]);}
            if(File.Exists(marker)){if(changes.Count>0)return Error("PARTS_CAPTION_APPLIED_CHANGED","Correction changed after publication");return Ok(new{already_applied=true,project_modified=false,production_release_allowed=false});}
            if(FileSha256(Path.Combine(ReferenceRoot,@"artifacts\motor_forward_reverse.design.json"))!=Convert.ToString(plan["baseline_model_sha256"]))return Error("PARTS_CAPTION_MODEL_STALE","Model changed before annotation correction");
            foreach(var pair in (Dictionary<string,object>)plan["before_graphics"]){var page=FindTrialPage(trial,pair.Key);if(ClientHash(ser.Serialize(ClientGraphics(page)))!=Convert.ToString(pair.Value))return Error("PARTS_CAPTION_GRAPHICS_CHANGED",pair.Key);}
            trial.LockAllObjects();foreach(var pair in changes){var value=new MultiLangString();value.AddString(ISOCode.Language.L_zh_CN,pair.Value);pair.Key.Contents=value;}
            string a0=Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0_applied.json");var geometry=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(a0,Encoding.UTF8));var hashes=new Dictionary<string,object>();foreach(Page p in trial.Pages)hashes[p.IdentifyingName]=ClientHash(ser.Serialize(ClientGraphics(p)));geometry["post_page_sha256"]=hashes;geometry["parts_caption_revision"]="parts-caption-A1";File.WriteAllText(a0,ser.Serialize(geometry),Encoding.UTF8);
            var result=new{revision="parts-caption-A1",plan_sha256=CuratedDocPlanHash,captions_updated=changes.Count,native_edges=ChineseEdges(trial).Count,construction_release_allowed=false};File.WriteAllText(marker,ser.Serialize(result),Encoding.UTF8);return Ok(result);
        }
        private Project CuratedTrial(ProjectManager pm,Project[] projects)
        {
            string path=Path.Combine(ReferenceRoot,@"workspace\motor_forward_reverse_trial.elk");
            foreach(Project p in projects)if(String.Equals(p.ProjectLinkFilePath,path,StringComparison.OrdinalIgnoreCase))return p;
            return pm.OpenProject(path);
        }
        private Dictionary<string,object> InspectCuratedParts(ProjectManager pm,Project[] projects)
        {
            var p=CuratedTrial(pm,projects);var articles=new List<object>();var functions=new List<object>();
            foreach(Eplan.EplApi.DataModel.Article a in p.Articles)articles.Add(new{part_number=a.PartNr,variant=a.VariantNr,manufacturer=a.Properties.ARTICLE_MANUFACTURER.ToString(),order_number=a.Properties.ARTICLE_ORDERNR.ToString(),description=a.Properties.ARTICLE_DESCR1.ToString(ISOCode.Language.L_zh_CN),note=a.Properties.ARTICLE_NOTE.ToString(ISOCode.Language.L_zh_CN),width_mm=a.Properties.ARTICLE_WIDTH.IsEmpty?(double?)null:a.Properties.ARTICLE_WIDTH.ToDouble(),height_mm=a.Properties.ARTICLE_HEIGHT.IsEmpty?(double?)null:a.Properties.ARTICLE_HEIGHT.ToDouble(),depth_mm=a.Properties.ARTICLE_DEPTH.IsEmpty?(double?)null:a.Properties.ARTICLE_DEPTH.ToDouble()});
            foreach(Page page in p.Pages)foreach(Function f in page.Functions)
            {
                var refs=new List<object>();foreach(ArticleReference a in f.ArticleReferences)refs.Add(new{part_number=a.PartNr,variant=a.VariantNr,count=a.Count,project_article_available=a.Article!=null});
                var terminal=f as Terminal;
                functions.Add(new{object_id=f.ObjectIdentifier,type_id=f.TypeIdentifier,page=page.IdentifyingName,name=f.Name,visible_name=f.VisibleName,symbol=f.SymbolVariant==null?null:f.SymbolVariant.SymbolName,is_main_function=f.IsMainFunction,is_main_terminal=terminal!=null&&terminal.SymbolVariant.SymbolName=="X"?(bool?)terminal.IsMainTerminal:null,article_references=refs});
            }
            return Ok(new{instance_id=instanceId,project=p.ProjectLinkFilePath,articles=articles,functions=functions,native_edges=ChineseEdges(p),project_modified=false,scope="project_articles_and_references_only",system_parts_database_modified=false,construction_release_allowed=false});
        }
        private static Eplan.EplApi.DataModel.Article CuratedArticle(Project p,string key)
        {Eplan.EplApi.DataModel.Article found=null;foreach(Eplan.EplApi.DataModel.Article a in p.Articles)if(a.PartNr==key && a.VariantNr=="1"){if(found!=null)throw new InvalidOperationException("Ambiguous project article");found=a;}return found;}
        private static void CuratedCheckArticle(Eplan.EplApi.DataModel.Article a,Dictionary<string,object> row)
        {
            if(a==null||a.Properties.ARTICLE_ORDERNR.ToString()!=Convert.ToString(row["order_number"])||a.Properties.ARTICLE_MANUFACTURER.ToString()!=Convert.ToString(row["manufacturer"])||a.Properties.ARTICLE_DESCR1.ToString(ISOCode.Language.L_zh_CN)!=Convert.ToString(row["description"])||a.Properties.ARTICLE_NOTE.ToString(ISOCode.Language.L_zh_CN).IndexOf(CuratedPartsPlanHash,StringComparison.Ordinal)<0)throw new InvalidOperationException("Curated record metadata differs: "+row["part_key"]);
            foreach(var pair in (Dictionary<string,object>)row["dimensions_mm"]){double actual=pair.Key=="width"?a.Properties.ARTICLE_WIDTH.ToDouble():pair.Key=="height"?a.Properties.ARTICLE_HEIGHT.ToDouble():a.Properties.ARTICLE_DEPTH.ToDouble();if(Math.Abs(actual-Convert.ToDouble(pair.Value))>.001)throw new InvalidOperationException("Curated body dimension differs");}
        }
        private Dictionary<string,object> ApplyCuratedParts(ProjectManager pm,Project[] projects,bool reconcile,bool probe=false)
        {
            string path=Path.Combine(ReferenceRoot,@"artifacts\curated_parts_A1.plan.json"),marker=Path.Combine(ReferenceRoot,@"artifacts\curated_parts_A1_applied.json"),partial=Path.Combine(ReferenceRoot,@"artifacts\curated_parts_A1_partial.json");
            if(FileSha256(path)!=CuratedPartsPlanHash)return Error("CURATED_PLAN_HASH_MISMATCH","Compiled project-local part plan differs");
            var ser=new JavaScriptSerializer();var plan=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(path,Encoding.UTF8));
            if(Convert.ToString(plan["schema"])!="project-curated-parts-1"||(bool)plan["system_database_write"]||(bool)plan["construction_release_allowed"])return Error("CURATED_SCOPE_INVALID","Only project-local sourced records are supported");
            if(File.Exists(marker)){var committed=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(marker,Encoding.UTF8));if(Convert.ToString(committed["plan_sha256"])!=CuratedPartsPlanHash || !(bool)committed["complete"])return Error("CURATED_COMMIT_PLAN_MISMATCH","Part commit belongs to another or incomplete plan");}
            var state=ApplyClientEngineering(pm,projects,true);if(!(bool)state["ok"])return state;
            Project trial=CuratedTrial(pm,pm.OpenProjects);var expected=new SortedSet<string>();foreach(object e in (object[])plan["expected_native_edges"])expected.Add(Convert.ToString(e));
            if(expected.Count!=161||!expected.SetEquals(ChineseEdges(trial)))return Error("CURATED_GRAPH_STALE","Native wiring changed");
            if(!File.Exists(marker)&&FileSha256(Path.Combine(ReferenceRoot,@"artifacts\motor_forward_reverse.design.json"))!=Convert.ToString(plan["baseline_model_sha256"]))return Error("CURATED_MODEL_STALE","Design changed before project part binding");
            var definitions=new Dictionary<string,Dictionary<string,object>>();foreach(object obj in (object[])plan["definitions"]){var row=(Dictionary<string,object>)obj;string key=Convert.ToString(row["part_key"]);if(!key.StartsWith("CODEX.CURATED.A1.",StringComparison.Ordinal)||definitions.ContainsKey(key))return Error("CURATED_KEY_INVALID","Owned part identifiers required");definitions[key]=row;var existing=CuratedArticle(trial,key);if(existing!=null)CuratedCheckArticle(existing,row);}
            var targets=new Dictionary<long,Function>();var wanted=new Dictionary<long,HashSet<string>>();
            foreach(object obj in (object[])plan["bindings"]){var row=(Dictionary<string,object>)obj;long id=Convert.ToInt64(row["object_id"]);var f=ClientFunction(trial,id);string key=Convert.ToString(row["part_key"]);if(!definitions.ContainsKey(key)||Convert.ToInt32(row["count"])!=1||f.TypeIdentifier!=Convert.ToInt32(row["type_id"])||f.Name!=Convert.ToString(row["name"])||f.SymbolVariant.SymbolName!=Convert.ToString(row["symbol"])||f.Page.IdentifyingName!=Convert.ToString(row["page"]))return Error("CURATED_FUNCTION_STALE","Part target changed");targets[id]=f;if(!wanted.ContainsKey(id))wanted[id]=new HashSet<string>();if(!wanted[id].Add(key))return Error("CURATED_DUPLICATE_BINDING","Duplicate planned reference");}
            foreach(object obj in (object[])plan["bindings"]){var row=(Dictionary<string,object>)obj;if(!(bool)row["main_terminal"] && targets[Convert.ToInt64(row["object_id"])].IsMainFunction!=(bool)row["main_function_before"])return Error("CURATED_MAIN_FUNCTION_CHANGED","Preserve a changed part ownership function");}
            var missing=new List<Dictionary<string,object>>();var verified=new List<object>();
            foreach(var target in targets){var seen=new HashSet<string>();foreach(ArticleReference reference in target.Value.ArticleReferences){if(reference.Count<=0||reference.PartNr=="")continue;if(!wanted[target.Key].Contains(reference.PartNr)||!seen.Add(reference.PartNr)||Convert.ToDouble(reference.Count)!=1||reference.Article==null)return Error("CURATED_REFERENCE_CONFLICT","Preserve unrelated, duplicate or changed part reference");CuratedCheckArticle(reference.Article,definitions[reference.PartNr]);}}
            foreach(object obj in (object[])plan["bindings"]){var row=(Dictionary<string,object>)obj;var f=targets[Convert.ToInt64(row["object_id"])];ArticleReference found=null;foreach(ArticleReference reference in f.ArticleReferences)if(reference.Count>0&&reference.PartNr==Convert.ToString(row["part_key"]))found=reference;if(found==null)missing.Add(row);else verified.Add(new{object_id=f.ObjectIdentifier,tag=row["tag"],part_key=found.PartNr,count=found.Count,project_article_available=true});}
            if(reconcile && missing.Count>0)return Error("CURATED_BINDING_INCOMPLETE",missing.Count+" source-defined references remain unbound");
            if(reconcile){foreach(object obj in (object[])plan["bindings"]){var row=(Dictionary<string,object>)obj;if((bool)row["main_terminal"]&&!((Terminal)targets[Convert.ToInt64(row["object_id"])]).IsMainTerminal)return Error("CURATED_MAIN_TERMINAL_CHANGED","Main terminal ownership changed");}if(!File.Exists(marker))return Error("CURATED_COMMIT_MARKER_MISSING","All references must be committed by the fixed apply operation");}
            int written=0;string stage="preflight";
            try
            {
                if(!reconcile && missing.Count>0)
                {
                    trial.LockAllObjects();
                    foreach(var row in missing)
                    {
                        long id=Convert.ToInt64(row["object_id"]);if(probe && id!=Convert.ToInt64(plan["probe_object_id"]))continue;
                        if(written>=(probe?1:Convert.ToInt32(plan["batch_size"])))break;
                        string key=Convert.ToString(row["part_key"]);var definition=definitions[key];var f=targets[id];stage="create owned project article "+key;
                        var article=CuratedArticle(trial,key);
                        if(article==null)
                        {
                            article=new Eplan.EplApi.DataModel.Article();article.Create(trial,key,"1");
                            var note=new MultiLangString();note.AddString(ISOCode.Language.L_zh_CN,"CODEX_CURATED_PROJECT_RECORD | plan="+CuratedPartsPlanHash+" | 依据厂家资料人工整理，不是厂家原始宏/认证数据；未批准采购、施工或投运。 "+String.Join(",",Array.ConvertAll((object[])definition["source_ids"],x=>Convert.ToString(x))));article.Properties.ARTICLE_NOTE=note;
                            article.Properties.ARTICLE_MANUFACTURER=Convert.ToString(definition["manufacturer"]);article.Properties.ARTICLE_ORDERNR=Convert.ToString(definition["order_number"]);article.Properties.ARTICLE_TYPENR=Convert.ToString(definition["order_number"]);
                            var description=new MultiLangString();description.AddString(ISOCode.Language.L_zh_CN,Convert.ToString(definition["description"]));article.Properties.ARTICLE_DESCR1=description;
                            foreach(var pair in (Dictionary<string,object>)definition["dimensions_mm"]){double value=Convert.ToDouble(pair.Value);if(pair.Key=="width")article.Properties.ARTICLE_WIDTH=value;else if(pair.Key=="height")article.Properties.ARTICLE_HEIGHT=value;else if(pair.Key=="depth")article.Properties.ARTICLE_DEPTH=value;else throw new InvalidOperationException("Unsupported body dimension");}
                            CuratedCheckArticle(article,definition);
                        }
                        stage="bind existing function "+row["tag"];
                        if((bool)row["main_terminal"]){var terminal=f as Terminal;if(terminal==null||terminal.SymbolVariant.SymbolName!="X")throw new InvalidOperationException("Expected single-level terminal");terminal.IsMainTerminal=true;}
                        var bound=f.AddArticleReference(key,"1",1u);
                        if(bound==null||bound.PartNr!=key||Convert.ToDouble(bound.Count)!=1||bound.Article==null)throw new InvalidOperationException("Native article reference did not read back");
                        CuratedCheckArticle(bound.Article,definition);written++;
                        verified.Add(new{object_id=f.ObjectIdentifier,tag=row["tag"],part_key=bound.PartNr,count=bound.Count,project_article_available=true});
                    }
                }
                if(!expected.SetEquals(ChineseEdges(trial)))throw new InvalidOperationException("Unexpected wire changes during metadata-only operation");
                bool complete=verified.Count==((object[])plan["bindings"]).Length;
                var result=new{revision="project-curated-parts-A1",plan_sha256=CuratedPartsPlanHash,expected_bindings=((object[])plan["bindings"]).Length,verified_bindings=verified.Count,definitions=definitions.Count,references=verified,complete=complete,written_this_call=written,native_edges=161,system_database_modified=false,manufacturer_macros_imported=false,construction_release_allowed=false};
                if(complete && !reconcile){if(!File.Exists(marker))File.WriteAllText(marker,ser.Serialize(result),Encoding.UTF8);else{var committed=(Dictionary<string,object>)ser.DeserializeObject(File.ReadAllText(marker,Encoding.UTF8));if(Convert.ToString(committed["plan_sha256"])!=CuratedPartsPlanHash)return Error("CURATED_COMMIT_PLAN_MISMATCH","Part commit belongs to another plan");}if(File.Exists(partial))File.Move(partial,Path.Combine(ReferenceRoot,@"artifacts\curated_parts_A1_partial_completed_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss")+".json"));}
                else if(!complete)File.WriteAllText(partial,ser.Serialize(result),Encoding.UTF8);
                return Ok(result);
            }
            catch(Exception ex){File.WriteAllText(partial,ser.Serialize(new{stage=stage,error=ex.Message,state="PARTIAL_METADATA_REQUIRES_INSPECTION",whole_project_rollback_claimed=false,production_release_allowed=false}),Encoding.UTF8);return Error("CURATED_PARTIAL_METADATA_WRITE",stage+": "+ex.Message);}
        }
    }
}
