using System;
using System.IO;
using System.Collections.Generic;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.EObjects;
using Eplan.EplApi.HEServices;
using DrawingText=Eplan.EplApi.DataModel.Graphics.Text;

namespace AiCae.Eplan
{
    public static partial class WorkstationNative
    {
        static object SafetyNotes(Project project,string root,string notesHash)
        {
            string path=Rooted(root,"workstation-safety-notes.json"),statePath=Rooted(root,"native-objects.json");
            if(String.IsNullOrEmpty(notesHash)||Hash(path)!=notesHash)throw new InvalidDataException("Annotation fingerprint mismatch");
            var p=Load(path);var state=Load(statePath);
            if(S(p,"schema_version")!="eplan-workstation-safety-notes-1"||S(p,"parent_safety_sha256")!=S(state,"safety_revision")||Hash(statePath)!=S(p,"baseline_state_sha256"))throw new InvalidDataException("Annotation parent/preimage changed");
            if(state.ContainsKey("safety_notes_started"))
            {
                if(!state.ContainsKey("safety_notes_sha256")||S(state,"safety_notes_started")!=S(state,"safety_notes_sha256"))throw new InvalidOperationException("Previous annotation outcome incomplete; inspect before recovery");
                if(S(state,"safety_notes_sha256")==notesHash||!p.ContainsKey("parent_notes_sha256")||S(p,"parent_notes_sha256")!=S(state,"safety_notes_sha256"))throw new InvalidDataException("Annotation revision chain mismatch; never replay");
            }
            var owned=ReadOwned(project,state);var before=NativeEdges(project);if(!before.SetEquals(ExpectedEdges((object[])state["effective_routes"],owned)))throw new InvalidDataException("Annotation graph precondition failed");
            var ts=new Dictionary<string,DrawingText>();foreach(Page pg in project.Pages)foreach(Placement pl in pg.AllGraphicalPlacements){var t=pl as DrawingText;if(t!=null)ts[Key(t)]=t;}
            foreach(object o in (object[])p["changes"]){var c=Dict(o);string key=S(c,"native_key");if(!ts.ContainsKey(key))throw new InvalidDataException("Annotation object missing");var t=ts[key];if(t.Contents.GetString(ISOCode.Language.L_zh_CN)!=S(c,"old_text")||Math.Abs(t.Location.X-Convert.ToDouble(c["old_x"]))>.01||Math.Abs(t.Location.Y-Convert.ToDouble(c["old_y"]))>.01||(c.ContainsKey("old_height")&&Math.Abs(t.Height-Convert.ToDouble(c["old_height"]))>.01))throw new InvalidDataException("Annotation preimage changed");}
            foreach(object o in (object[])p["function_texts"]){var c=Dict(o);if(owned[S(c,"id")].Properties.FUNC_TEXT.ToString(ISOCode.Language.L_zh_CN)!=S(c,"old_text"))throw new InvalidDataException("Native function text preimage changed");}
            foreach(object o in (object[])p["contact_images"]){var c=Dict(o);var ci=owned[S(c,"id")].ContactImage;if(ci==null)throw new InvalidDataException("Contact image missing");if(Math.Abs(ci.Location.X-Convert.ToDouble(c["old_x"]))>.01||Math.Abs(ci.Location.Y-Convert.ToDouble(c["old_y"]))>.01||ci.AutoAlign!=Convert.ToBoolean(c["old_auto_align"])||ci.IsOnComponent!=Convert.ToBoolean(c["old_on_component"]))throw new InvalidDataException("Preserve modified contact image");}
            state["safety_notes_started"]=notesHash;Save(statePath,state);project.LockAllObjects();
            foreach(object o in (object[])p["changes"]){var c=Dict(o);var t=ts[S(c,"native_key")];t.Contents=Zh(S(c,"new_text"));t.Location=new PointD(Convert.ToDouble(c["x"]),Convert.ToDouble(c["y"]));if(c.ContainsKey("height"))t.Height=Convert.ToDouble(c["height"]);}
            foreach(object o in (object[])p["function_texts"]){var c=Dict(o);owned[S(c,"id")].Properties.FUNC_TEXT=Zh(S(c,"new_text"));}
            foreach(object o in (object[])p["contact_images"]){var c=Dict(o);var f=owned[S(c,"id")];var ci=f.ContactImage;ci.RelativeLocation=new PointD(Convert.ToDouble(c["x"])-f.Location.X,Convert.ToDouble(c["y"])-f.Location.Y);ci.AutoAlign=false;}
            if(!before.SetEquals(NativeEdges(project)))throw new InvalidDataException("Annotation unexpectedly changed native connections");
            state["safety_notes_sha256"]=notesHash;Save(statePath,state);
            return new{native_edges_unchanged=true,edges=before.Count,changed_texts=((object[])p["changes"]).Length,contact_images=((object[])p["contact_images"]).Length,construction_release=false};
        }
        // One explicit, hash-bound revision. No arbitrary project/code/action input.
        static object ApplySafety(Project project,Dictionary<string,object> basePlan,string root,string baseHash,string safetyHash)
        {
            string path=Rooted(root,"workstation-safety-R2.json"),statePath=Rooted(root,"native-objects.json");
            if(String.IsNullOrEmpty(safetyHash)||Hash(path)!=safetyHash)throw new InvalidDataException("Safety revision fingerprint mismatch");
            var plan=Load(path);var state=Load(statePath);
            if(S(plan,"schema_version")!="eplan-workstation-safety-2"||S(plan,"base_plan_sha256")!=baseHash||S(state,"plan_sha256")!=baseHash)throw new InvalidDataException("Safety parent/schema mismatch");
            if(state.ContainsKey("safety_revision")||state.ContainsKey("safety_started"))throw new InvalidOperationException("Safety revision already started; read back before any recovery, never replay");
            if(Hash(statePath)!=S(plan,"baseline_state_sha256"))throw new InvalidDataException("Safety state precondition changed");
            var owned=ReadOwned(project,state);var baseline=Dict(plan["baseline_snapshot"]);
            if(owned.Count!=Convert.ToInt32(plan["baseline_functions"])||NativeEdges(project).Count!=Convert.ToInt32(plan["baseline_edges"])||!NativeEdges(project).SetEquals(ExpectedEdges((object[])state["effective_routes"],owned)))throw new InvalidDataException("Safety baseline graph changed");
            foreach(object o in (object[])baseline["functions"])
            {
                var b=Dict(o);var f=owned[S(b,"id")];
                if(Key(f)!=S(b,"native_key")||f.Name!=S(b,"name")||f.IsMainFunction!=Convert.ToBoolean(b["main"]))throw new InvalidDataException("Baseline function semantics changed: "+S(b,"id"));
                foreach(object po in (object[])b["pins"])
                {var p=Dict(po);int i=Convert.ToInt32(p["index"]);if(f.Properties.FUNC_CONNECTIONDESIGNATION[i+1].ToString()!=S(p,"displayed_designation")||f.Pins[i].Signal.ToString()!=S(p,"signal")||f.Pins[i].Potential.ToString()!=S(p,"potential")||f.Pins[i].MaxConnectionCount!=Convert.ToInt32(p["max_connections"]))throw new InvalidDataException("Baseline pin changed");}
                if(f.SymbolVariant.SymbolName=="PLCCP"&&(f.Properties.FUNC_PLCADDRESS.ToString()!=S(b,"address")||f.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.ToString()!=S(b,"variable")))throw new InvalidDataException("PLC baseline changed");
            }
            var texts=new Dictionary<string,DrawingText>();var ips=new Dictionary<string,InterruptionPoint>();
            foreach(Page pg in project.Pages)
            {
                foreach(Placement pl in pg.AllGraphicalPlacements){var t=pl as DrawingText;if(t!=null)texts[Key(t)]=t;}
                foreach(Placement pl in pg.AllPlacements){var ip=pl as InterruptionPoint;if(ip!=null)ips[Key(ip)]=ip;}
            }
            if(texts.Count!=((object[])baseline["texts"]).Length||ips.Count!=((object[])baseline["interruptions"]).Length)throw new InvalidDataException("Baseline text/interruption inventory changed");
            foreach(object o in (object[])baseline["texts"])
            {var b=Dict(o);string k=S(b,"native_key");if(!texts.ContainsKey(k))throw new InvalidDataException("Baseline text missing");var t=texts[k];if(t.Contents.GetString(ISOCode.Language.L_zh_CN)!=S(b,"text")||t.Page.IdentifyingName!=S(b,"page")||Math.Abs(t.Location.X-Convert.ToDouble(b["x"]))>.01||Math.Abs(t.Location.Y-Convert.ToDouble(b["y"]))>.01)throw new InvalidDataException("Preserve modified drawing text: "+k);}
            foreach(object o in (object[])baseline["interruptions"])
            {var b=Dict(o);string k=S(b,"native_key");if(!ips.ContainsKey(k))throw new InvalidDataException("Baseline interruption missing");var ip=ips[k];if(ip.VisibleName!=S(b,"visible")||ip.IsStarSource!=Convert.ToBoolean(b["source"])||Math.Abs(ip.Location.X-Convert.ToDouble(b["x"]))>.01||Math.Abs(ip.Location.Y-Convert.ToDouble(b["y"]))>.01)throw new InvalidDataException("Baseline interruption changed");}
            var plannedIps=Dict(state["attachments"]);if(plannedIps.Count!=ips.Count)throw new InvalidDataException("Unowned interruption inventory");
            foreach(var a in plannedIps)if(!ips.ContainsKey(S(Dict(a.Value),"native_key")))throw new InvalidDataException("Owned interruption missing");
            foreach(object o in (object[])plan["new_pages"])foreach(Page pg in project.Pages)if(pg.IdentifyingName=="/"+S(Dict(o),"number"))throw new InvalidDataException("New revision page already exists");
            foreach(object o in (object[])plan["rewrite_graphic_pages"])
            {
                var rw=Dict(o);Page pg=GetPage(project,Convert.ToInt32(rw["page"]),basePlan);if(pg.Functions.Length!=0)throw new InvalidDataException("Cannot rewrite a schematic page as a text table");
                var actualKeys=new HashSet<string>();foreach(var t in texts)if(t.Value.Page==pg)actualKeys.Add(t.Key);
                var expectedKeys=new HashSet<string>();foreach(object k in (object[])rw["expected_native_keys"])expectedKeys.Add(Convert.ToString(k));if(!actualKeys.SetEquals(expectedKeys))throw new InvalidDataException("Table page changed");
            }
            // Validate the full delta before touching native state.
            var specs=new Dictionary<string,Dictionary<string,object>>();
            foreach(object o in (object[])plan["new_functions"]){var s=Dict(o);if(owned.ContainsKey(S(s,"id"))||specs.ContainsKey(S(s,"id")))throw new InvalidDataException("New function collides");specs[S(s,"id")]=s;}
            var endpointUse=new HashSet<string>();var groupNames=new HashSet<string>();
            foreach(object o in (object[])plan["route_groups"])
            {
                var g=Dict(o);if(!groupNames.Add(S(g,"name")))throw new InvalidDataException("Duplicate route group");var ends=(object[])g["ends"];if(ends.Length<2||ends.Length>3)throw new InvalidDataException("Route arity invalid");
                for(int i=0;i<ends.Length;i++){var e=Dict(ends[i]);string id=S(e,"function_id");int pi=Convert.ToInt32(e["pin_index"]);if(!owned.ContainsKey(id)&&!specs.ContainsKey(id))throw new InvalidDataException("Unknown route function");if(!endpointUse.Add(id+":"+pi))throw new InvalidDataException("Pin belongs to multiple route groups");if(owned.ContainsKey(id)){var f=owned[id];int cap=f.SymbolVariant.SymbolName=="PLCCP"?1:f.Pins[pi].MaxConnectionCount;if(cap<(i==0?ends.Length-1:1))throw new InvalidDataException("Native pin capacity exceeded");}}
            }
            // Immutable preimage plus marker: an exception below requires inspection.
            Save(Rooted(root,"before-safety-R2-state.json"),state);state["safety_started"]=safetyHash;Save(statePath,state);project.LockAllObjects();
            var merged=Dict(J().DeserializeObject(J().Serialize(basePlan)));var funcs=new List<object>((object[])merged["functions"]);funcs.AddRange((object[])plan["new_functions"]);merged["functions"]=funcs.ToArray();var pages=new List<object>((object[])merged["pages"]);pages.AddRange((object[])plan["new_pages"]);merged["pages"]=pages.ToArray();
            foreach(object o in (object[])plan["new_pages"]){var pg=Dict(o);GetPage(project,Convert.ToInt32(pg["number"]),merged).Properties.PAGE_NOMINATIOMN=Zh(S(pg,"name"));}
            foreach(var ip in ips.Values)ip.Remove();
            // Only remove owned BPIN captions by exact route-name text. Tables use
            // full rows, and are handled separately after their keyset preflight.
            var oldNames=new HashSet<string>();foreach(object o in (object[])state["effective_routes"])oldNames.Add(S(Dict(o),"name"));
            foreach(var t in texts)if(oldNames.Contains(t.Value.Contents.GetString(ISOCode.Language.L_zh_CN)))t.Value.Remove();
            foreach(object o in (object[])plan["moves"]){var m=Dict(o);string id=S(m,"id");var f=owned[id];f.Location=new PointD(Convert.ToDouble(m["x"]),Convert.ToDouble(m["y"]));Dict(Dict(state["objects"])[id])["x"]=f.Location.X;Dict(Dict(state["objects"])[id])["y"]=f.Location.Y;}Save(statePath,state);
            foreach(object o in (object[])plan["pin_changes"]){var c=Dict(o);var f=owned[S(c,"id")];foreach(var p in Dict(c["labels"]))f.Properties.FUNC_CONNECTIONDESIGNATION[Int32.Parse(p.Key)+1]=Convert.ToString(p.Value);}
            foreach(object o in (object[])plan["new_functions"])
            {
                var spec=Dict(o);Page pg=GetPage(project,Convert.ToInt32(spec["page"]),merged);var oldTexts=new HashSet<string>();foreach(Placement pl in pg.AllGraphicalPlacements){var t=pl as DrawingText;if(t!=null)oldTexts.Add(Key(t));}
                var f=EnsureFunction(project,merged,spec,state,owned,statePath);var generated=new List<DrawingText>();foreach(Placement pl in pg.AllGraphicalPlacements){var t=pl as DrawingText;if(t!=null&&!oldTexts.Contains(Key(t)))generated.Add(t);}foreach(var t in generated)t.Remove();FormattedLabels(f,spec);
                if(S(spec,"kind")=="function")foreach(PinBase gp in f.GraphicalConnectionPoints){string dir=gp.Direction.ToString();Text(pg,f.Location.X+gp.Location.X+(dir=="Left"?-8:3),f.Location.Y+gp.Location.Y+(dir=="Up"?2:-3),ShortPin(spec,gp.Index.ToString()),2.0);}
            }
            foreach(object o in (object[])plan["text_changes"]){var c=Dict(o);var t=texts[S(c,"native_key")];if(t.Contents.GetString(ISOCode.Language.L_zh_CN)!=S(c,"old_text"))throw new InvalidDataException("Caption precondition changed");t.Contents=Zh(S(c,"new_text"));t.Location=new PointD(Convert.ToDouble(c["x"]),Convert.ToDouble(c["y"]));}
            foreach(object o in (object[])plan["rewrite_graphic_pages"]){var rw=Dict(o);Page pg=GetPage(project,Convert.ToInt32(rw["page"]),merged);foreach(object k in (object[])rw["expected_native_keys"])texts[Convert.ToString(k)].Remove();foreach(object to in (object[])rw["texts"]){var t=Dict(to);Text(pg,Convert.ToDouble(t["x"]),Convert.ToDouble(t["y"]),S(t,"text"),Convert.ToDouble(t["height"]));}}
            foreach(object o in (object[])plan["texts"]){var t=Dict(o);Text(GetPage(project,Convert.ToInt32(t["page"]),merged),Convert.ToDouble(t["x"]),Convert.ToDouble(t["y"]),S(t,"text"),Convert.ToDouble(t["height"]));}
            var direct=new HashSet<string>();foreach(object o in (object[])plan["direct_groups"])direct.Add(Convert.ToString(o));var attached=new Dictionary<string,object>();
            foreach(object o in (object[])plan["route_groups"])
            {
                var g=Dict(o);var ends=(object[])g["ends"];if(direct.Contains(S(g,"name")))continue;
                for(int i=0;i<ends.Length;i++){var e=Dict(ends[i]);string id=S(e,"function_id");int pi=Convert.ToInt32(e["pin_index"]);var f=owned[id];int cap=f.SymbolVariant.SymbolName=="PLCCP"?1:f.Pins[pi].MaxConnectionCount;if(cap<(i==0?ends.Length-1:1))throw new InvalidDataException("New function pin capacity exceeded");var ip=Attach(project,f,pi,S(g,"name"),i==0,100+i,2.2);attached[S(g,"name")+":"+i]=new{native_key=Key(ip),parent=id,pin_index=pi};}
            }
            state["attachments"]=attached;state["effective_routes"]=plan["route_groups"];state["direct_groups"]=plan["direct_groups"];state["safety_revision"]=safetyHash;state["safety_model_sha256"]=plan["new_model_sha256"];state["machine_safety_validated"]=false;Save(statePath,state);
            using(var gen=new Generate())gen.Connections(project,false);
            var expected=ExpectedEdges((object[])plan["route_groups"],owned);var actual=NativeEdges(project);bool match=actual.SetEquals(expected);
            state["safety_edge_match"]=match;Save(statePath,state);
            if(!match)throw new InvalidDataException("Safety delta has missing/unexpected native edges; inspect saved state and read back, never replay");
            return new{revision=S(plan,"revision"),safety_sha256=safetyHash,new_model_sha256=S(plan,"new_model_sha256"),native_functions=owned.Count,expected_edges=expected.Count,actual_edges=actual.Count,typed_edge_set_matches=match,missing=Except(expected,actual),unexpected=Except(actual,expected),machine_safety_validated=false,construction_release=false};
        }
    }
}
