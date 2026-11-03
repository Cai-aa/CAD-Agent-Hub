using System;
using System.IO;
using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using Eplan.EplApi.Base;
using Eplan.EplApi.ApplicationFramework;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.MasterData;
using Eplan.EplApi.DataModel.EObjects;
using Eplan.EplApi.HEServices;
using Eplan.EplApi.EServices;
using DrawingText=Eplan.EplApi.DataModel.Graphics.Text;
using DrawingRectangle=Eplan.EplApi.DataModel.Graphics.Rectangle;

namespace AiCae.Eplan
{
    // A typed workstation authoring adapter, independent of the legacy motor trial.
    public static partial class WorkstationNative
    {
        static JavaScriptSerializer J() { return new JavaScriptSerializer { MaxJsonLength=16*1024*1024 }; }
        static string Hash(string path) { using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(File.ReadAllBytes(path))).Replace("-","").ToLowerInvariant(); }
        static string S(Dictionary<string,object> d,string key) {return Convert.ToString(d[key]);}
        static Dictionary<string,object> Dict(object x) {return (Dictionary<string,object>)x;}
        static string Local(string path) {if(!Path.IsPathRooted(path)||path.StartsWith(@"\\"))throw new InvalidDataException("Absolute local path required");return Path.GetFullPath(path);}
        static MultiLangString Zh(string value) {var m=new MultiLangString();m.AddString(ISOCode.Language.L_zh_CN,value);return m;}
        static void Save(string path,object value) {File.WriteAllText(path,J().Serialize(value),new UTF8Encoding(false));}
        static Dictionary<string,object> Load(string path) {return Dict(J().DeserializeObject(File.ReadAllText(path,Encoding.UTF8)));}
        static string Rooted(string root,string name)
        {
            string p=Local(Path.Combine(root,name));
            if(!p.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Path escapes authoring root");
            return p;
        }
        public static string Execute(string command,string workspace,string planPath,string expectedHash,int pageNumber,string formatHash)
        {
            var output=new Dictionary<string,object>();
            output["command"]=command;output["pid"]=Process.GetCurrentProcess().Id;
            output["helper_mvid"]=typeof(WorkstationNative).Assembly.ManifestModule.ModuleVersionId.ToString();
            output["helper_assembly"]=typeof(WorkstationNative).Assembly.Location;
            output["executable"]=Process.GetCurrentProcess().MainModule.FileName;
            output["build"]=FileVersionInfo.GetVersionInfo(Process.GetCurrentProcess().MainModule.FileName).FileVersion;
            output["construction_release"]=false;
            try
            {
                if(command!="prepare" && command!="catalog" && command!="snapshot" && command!="apply_page" && command!="export" && command!="check" && command!="repair_sources" && command!="normalize" && command!="format" && command!="polish" && command!="inspect_reopen" && command!="bind_reopen" && command!="backup" && command!="safety_revision" && command!="safety_notes")throw new InvalidDataException("Command not allowed");
                if(Convert.ToString(output["build"])!="2.9.4.14642")throw new InvalidDataException("Native adapter requires the tested 2.9.4.14642 build");
                string root=Local(workspace).TrimEnd(Path.DirectorySeparatorChar);
                if(Hash(planPath)!=expectedHash)throw new InvalidDataException("Immutable plan hash mismatch");
                var plan=Load(planPath);
                if(S(plan,"schema_version")!="eplan-workstation-native-1")throw new InvalidDataException("Unsupported plan schema");
                string name=S(plan,"project_name");
                if(name!="Conveyor_Pusher_R1")throw new InvalidDataException("Only the dedicated new workstation is supported");
                string target=Rooted(root,name+".elk"),ownerPath=Rooted(root,"workstation-owner.json");
                using(var quiet=new QuietModeStep(QuietModes.ShowNoDialogs))
                using(var step=new LockingStep())
                using(var pm=new ProjectManager())
                {
                    Project project=null;foreach(Project p in pm.OpenProjects)if(String.Equals(p.ProjectLinkFilePath,target,StringComparison.OrdinalIgnoreCase))project=p;
                    if(command=="prepare")
                    {
                        if(File.Exists(target)||Directory.Exists(Path.ChangeExtension(target,".edb"))||File.Exists(ownerPath))throw new InvalidOperationException("Target already exists: inspect the owner and native state; no overwrite or retry");
                        Directory.CreateDirectory(root);
                        string template=Local(S(plan,"template"));if(!File.Exists(template))throw new FileNotFoundException("Explicit base template is missing",template);
                        project=pm.CreateProject(target,template);
                        if(project==null)throw new InvalidOperationException("CreateProject returned null; outcome unknown");
                        Save(ownerPath,new Dictionary<string,object>{{"project",target},{"database_id",project.DatabaseIdentifier},{"project_guid",project.Properties.PROJ_GUID.ToString()},{"last_bound_pid",Process.GetCurrentProcess().Id},{"model_sha256",S(plan,"model_sha256")},{"layout_sha256",""},{"created_utc",DateTime.UtcNow.ToString("o")}});
                        foreach(object obj in (object[])plan["pages"])
                        {
                            var spec=Dict(obj);int n=Convert.ToInt32(spec["number"]);
                            var props=new PagePropertyList();props.PAGE_COUNTER=n;
                            var page=new Page();page.Create(project,DocumentTypeManager.DocumentType.Circuit,props);
                            page.Properties.PAGE_NOMINATIOMN=Zh(S(spec,"name"));
                        }
                    }
                    else
                    {
                        if(!File.Exists(ownerPath))throw new InvalidOperationException("No owned workstation: do not operate on other projects");
                        var owner=Load(ownerPath);
                        if(S(owner,"project")!=target||S(owner,"model_sha256")!=S(plan,"model_sha256"))throw new InvalidDataException("Workstation/model identity mismatch");
                        if(project==null)project=pm.OpenProject(target);
                        if(command!="inspect_reopen"&&command!="bind_reopen")
                        {
                            if(Convert.ToString(project.DatabaseIdentifier)!=S(owner,"database_id")||(owner.ContainsKey("last_bound_pid")&&Convert.ToInt32(owner["last_bound_pid"])!=Process.GetCurrentProcess().Id))throw new InvalidDataException("Native project session identity changed; inspect and fully verify reopened identity before rebinding");
                            if(owner.ContainsKey("project_guid")&&S(owner,"project_guid")!=project.Properties.PROJ_GUID.ToString())throw new InvalidDataException("Persistent native project GUID changed");
                        }
                    }
                    output["project"]=project.ProjectLinkFilePath;output["database_id"]=project.DatabaseIdentifier;
                    if(command=="apply_page"||command=="repair_sources"||command=="normalize"||command=="format"||command=="polish")
                    {string sp=Rooted(root,"native-objects.json");if(File.Exists(sp)){var st=Load(sp);if(st.ContainsKey("safety_started"))throw new InvalidOperationException("R1 mutation retired after safety revision began; do not replay old plans");}}
                    if(command=="catalog")output["catalog"]=Catalog(project);
                    else if(command=="apply_page")output["apply"]=ApplyPage(project,plan,root,expectedHash,pageNumber);
                    else if(command=="export")output["export"]=ExportPdf(project,root);
                    else if(command=="check")output["verification"]=CheckProject(project);
                    else if(command=="repair_sources")output["repair"]=RepairSources(project,plan,root,expectedHash);
                    else if(command=="normalize")output["normalize"]=Normalize(project,plan,root,expectedHash);
                    else if(command=="format")output["format"]=FormatDrawing(project,plan,root,expectedHash,formatHash);
                    else if(command=="polish")output["polish"]=Polish(project,root,formatHash);
                    else if(command=="inspect_reopen"||command=="bind_reopen")output["identity"]=ReopenedIdentity(project,root,formatHash,command=="bind_reopen");
                    else if(command=="backup")output["backup"]=MakeBackup(project,root);
                    else if(command=="safety_revision")output["safety"]=ApplySafety(project,plan,root,expectedHash,formatHash);
                    else if(command=="safety_notes")output["notes"]=SafetyNotes(project,root,formatHash);
                    if(command=="snapshot"||command=="apply_page"||command=="repair_sources"||command=="normalize"||command=="format"||command=="polish"||command=="safety_revision"||command=="safety_notes")output["snapshot"]=Snapshot(project,root);
                    if(command!="backup")output["pages"]=Pages(project);
                    output["success"]=true;
                }
            }
            catch(Exception ex){output["success"]=false;output["error"]=ex.ToString();output["partial_write_possible"]=command=="prepare"||command=="apply_page"||command=="format"||command=="normalize"||command=="repair_sources"||command=="polish"||command=="safety_revision"||command=="safety_notes";}
            return J().Serialize(output);
        }
        static Page GetPage(Project p,int n,Dictionary<string,object> plan)
        {
            foreach(Page page in p.Pages)if(page.IdentifyingName=="/"+n)return page;
            Dictionary<string,object> spec=null;foreach(object o in (object[])plan["pages"])if(Convert.ToInt32(Dict(o)["number"])==n)spec=Dict(o);
            if(spec==null)throw new InvalidDataException("Page not planned: "+n);
            var props=new PagePropertyList();props.PAGE_COUNTER=n;var created=new Page();
            created.Create(p,S(spec,"type")=="Graphics"?DocumentTypeManager.DocumentType.Graphics:DocumentTypeManager.DocumentType.Circuit,props);
            return created;
        }
        static string Key(StorableObject f) {return f.DatabaseIdentifier+":"+f.TypeIdentifier+":"+f.ObjectIdentifier;}
        static Dictionary<string,Function> ReadOwned(Project project,Dictionary<string,object> state)
        {
            var native=new Dictionary<string,Function>();foreach(Page pg in project.Pages)foreach(Function f in pg.Functions)native[Key(f)]=f;
            var result=new Dictionary<string,Function>();var saved=Dict(state["objects"]);
            foreach(var row in saved)
            {
                var spec=Dict(row.Value);string key=S(spec,"native_key");
                if(!native.ContainsKey(key))throw new InvalidDataException("Owned native function disappeared: "+row.Key);
                var f=native[key];
                if(f.Page.IdentifyingName!=S(spec,"page")||f.SymbolVariant.SymbolName!=S(spec,"symbol")||Math.Abs(f.Location.X-Convert.ToDouble(spec["x"]))>.01||Math.Abs(f.Location.Y-Convert.ToDouble(spec["y"]))>.01)
                    throw new InvalidDataException("Native function changed: "+row.Key);
                result[row.Key]=f;native.Remove(key);
            }
            if(native.Count>0)throw new InvalidDataException("Unexpected functions in the owned project; preserve and inspect before further writes");
            return result;
        }
        static SymbolVariant Variant(Project p,Dictionary<string,object> spec)
        {var v=new SymbolVariant();v.Initialize(new Symbol(new SymbolLibrary(p,S(spec,"library")),S(spec,"symbol")),Convert.ToInt32(spec["variant"]));return v;}
        static void HideProperties(Function f)
        {
            if(!f.UseLocalPropertyPlacements)f.SwitchLocalPropertyPlacements(true);
            foreach(var pp in f.PropertyPlacements){pp.LockObject();pp.IsSetAsVisible=Placement.Visibility.Invisible;}
        }
        static void Text(Page pg,double x,double y,string value,double height)
        {
            var t=new DrawingText();t.Create(pg,Zh(value),height);t.Location=new PointD(x,y);
        }
        static Function EnsureFunction(Project project,Dictionary<string,object> plan,Dictionary<string,object> spec,Dictionary<string,object> state,Dictionary<string,Function> owned,string statePath)
        {
            string id=S(spec,"id");if(owned.ContainsKey(id))return owned[id];
            string kind=S(spec,"kind"),tag=S(spec,"tag");int page=Convert.ToInt32(spec["page"]);
            Page pg=GetPage(project,page,plan);var v=Variant(project,spec);Function f;
            if(kind=="terminal"||kind=="plc_channel")
            {
                string parentId=S(spec,kind=="terminal"?"strip_parent":"plc_parent");
                Dictionary<string,object> parentSpec=null;foreach(object obj in (object[])plan["functions"])if(S(Dict(obj),"id")==parentId)parentSpec=Dict(obj);
                if(parentSpec==null)throw new InvalidDataException("Parent not planned: "+parentId);
                Function parent=EnsureFunction(project,plan,parentSpec,state,owned,statePath);
                var t=new Terminal();
                if(kind=="terminal")t.Create((TerminalStrip)parent,pg,v);
                else{t.Create((PLC)parent,v);t.Page=pg;t.Name=tag;t.VisibleName=tag;}
                if(kind=="terminal")t.Properties.FUNC_PINORTERMINALNUMBER=S(spec,"terminal");
                else
                {
                    t.Properties.FUNC_PLCADDRESS=S(spec,"address");
                    t.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL=S(spec,"variable");
                    t.Pins[0].Signal=S(spec,"address").StartsWith("Q")?Pin.SignalType.DigitalOutput:Pin.SignalType.DigitalInput;
                }
                f=t;
            }
            else if(kind=="terminal_strip")
            {var strip=new TerminalStrip();strip.Create(pg);strip.Name=tag;strip.VisibleName=tag;strip.SetSymbolVariant(v,true);f=strip;}
            else if(kind=="plc_box")
            {var plc=new PLC();plc.Create(pg,v);plc.Name=tag;plc.VisibleName=tag;f=plc;}
            else
            {
                f=new Function();f.Create(pg,v);f.Name=tag;f.VisibleName=tag;
                var sy=new Symbol(new SymbolLibrary(project,S(spec,"library")),S(spec,"symbol"));
                if(!sy.Properties.FUNC_CATEGORY_GROUP_ID.IsEmpty)f.Properties.FUNC_CATEGORY_GROUP_ID=sy.Properties.FUNC_CATEGORY_GROUP_ID.ToString();
                f.SetSymbolVariant(v,true);
            }
            double x=Convert.ToDouble(spec["x"]),y=Convert.ToDouble(spec["y"]);
            f.Location=new PointD(x,y);f.IsMainFunction=Convert.ToBoolean(spec["main"]);
            if(kind=="box"||kind=="plc_box")f.SetLogicalArea(new PointD(x,y),new PointD(Convert.ToDouble(spec["x2"]),Convert.ToDouble(spec["y2"])));
            var labels=Dict(spec["pin_labels"]);var roles=Dict(spec["ports"]);var conductors=Dict(spec["conductors"]);
            if(f.GraphicalConnectionPoints.Length!=roles.Count||f.Pins.Length<roles.Count)throw new InvalidOperationException("Native pin count differs for "+id+"; graphical="+f.GraphicalConnectionPoints.Length+" logical="+f.Pins.Length);
            foreach(var pair in labels)
            {
                int index=Int32.Parse(pair.Key);f.Properties.FUNC_CONNECTIONDESIGNATION[index+1]=Convert.ToString(pair.Value);
                string conductor=S(conductors,pair.Key);
                if(conductor=="PE")f.Pins[index].Potential=Pin.PotentialType.PE;
                if(kind=="terminal")f.Pins[index].IsExtern=false;
            }
            f.Properties.FUNC_TEXT=Zh(S(spec,"description_zh"));HideProperties(f);
            owned[id]=f;
            Dict(state["objects"])[id]=new Dictionary<string,object>{{"native_key",Key(f)},{"page",f.Page.IdentifyingName},{"symbol",f.SymbolVariant.SymbolName},{"x",f.Location.X},{"y",f.Location.Y}};
            Save(statePath,state);
            if(kind=="box"||kind=="plc_box")Text(pg,x+4,Convert.ToDouble(spec["y2"])-6,S(spec,"description_zh"),2);
            else if(spec.ContainsKey("label_x"))
            {
                string display=kind=="plc_channel"?S(spec,"address")+"  "+S(labels,"0")+"  "+S(spec,"variable"):S(labels,"0");
                Text(pg,Convert.ToDouble(spec["label_x"]),Convert.ToDouble(spec["label_y"]),display,kind=="plc_channel"?1.8:1.7);
            }
            else
            {
                string title=tag+(kind=="terminal"?":"+S(spec,"terminal"):"");
                Text(pg,x+16,y+3,title,2.0);
                string desc=S(spec,"description_zh");if(desc.Length>19)desc=desc.Substring(0,19);
                Text(pg,x+16,y-3,desc,1.7);
            }
            return f;
        }
        static InterruptionPoint Attach(Project project,Function f,int index,string name,bool source,int sort,double font=1.5)
        {
            PinBase pin=null;foreach(PinBase candidate in f.GraphicalConnectionPoints)if(candidate.Index==index)pin=candidate;
            if(pin==null)throw new InvalidDataException("No native graphical pin "+index);
            double x=f.Location.X+pin.Location.X,y=f.Location.Y+pin.Location.Y;int variant=0;
            string direction=pin.Direction.ToString();
            if(direction=="Up"){y+=12;variant=1;}else if(direction=="Down"){y-=12;variant=3;}
            else if(direction=="Left"){x-=12;variant=2;}else if(direction=="Right"){x+=12;variant=0;}else throw new InvalidDataException("Unsupported pin direction");
            var v=new SymbolVariant();v.Initialize(new Symbol(new SymbolLibrary(project,"SPECIAL"),"BPIN"),variant);
            var ip=new InterruptionPoint();ip.Create(f.Page,v);ip.Name=name;ip.VisibleName=name;ip.Location=new PointD(x,y);if(!source)ip.Properties.INTERRUPTIONPOINT_SORT_CODE=sort;ip.IsStarSource=source;
            if(!ip.UseLocalPropertyPlacements)ip.SwitchLocalPropertyPlacements(true);
            foreach(var pp in ip.PropertyPlacements){pp.LockObject();pp.IsSetAsVisible=Placement.Visibility.Invisible;}
            Text(f.Page,x+(direction=="Left"?-13:direction=="Right"?1:-3),y+(direction=="Down"?-4:2),name,font);
            return ip;
        }
        static object RepairSources(Project project,Dictionary<string,object> plan,string root,string hash)
        {
            var state=Load(Rooted(root,"native-objects.json"));if(S(state,"plan_sha256")!=hash)throw new InvalidDataException("Plan identity mismatch");
            var owned=ReadOwned(project,state);var attached=Dict(state["attachments"]);var ips=new Dictionary<string,InterruptionPoint>();
            foreach(Page pg in project.Pages)foreach(Placement pl in pg.AllPlacements){var ip=pl as InterruptionPoint;if(ip!=null)ips[Key(ip)]=ip;}
            var sources=new List<InterruptionPoint>();
            foreach(object obj in (object[])plan["route_groups"])
            {
                var group=Dict(obj);var ends=(object[])group["ends"];
                for(int n=0;n<ends.Length;n++)
                {
                    string key=S(group,"name")+":"+n;
                    if(!attached.ContainsKey(key))throw new InvalidDataException("Missing owned interruption "+key);
                    string native=S(Dict(attached[key]),"native_key");
                    if(!ips.ContainsKey(native)||ips[native].VisibleName!=S(group,"name"))throw new InvalidDataException("Interruption identity changed: "+key);
                    if(n==0)sources.Add(ips[native]);
                }
            }
            project.LockAllObjects();int repaired=0;
            // Sorting a source after setting IsStarSource clears the source
            // flag in 2.9. Source flags are therefore assigned LAST.
            foreach(var source in sources)if(!source.IsStarSource){source.IsStarSource=true;repaired++;}
            foreach(var source in sources)if(!source.IsStarSource)throw new InvalidOperationException("Star source flag did not persist");
            using(var gen=new Generate())gen.Connections(project,false);
            foreach(var source in sources)if(!source.IsStarSource)throw new InvalidOperationException("Generation cleared a star source");
            return new{repaired_source_flags=repaired,verified_sources=sources.Count,geometry_changed=false};
        }
        static object Normalize(Project project,Dictionary<string,object> plan,string root,string hash)
        {
            string statePath=Rooted(root,"native-objects.json");var state=Load(statePath);
            if(S(state,"plan_sha256")!=hash)throw new InvalidDataException("Plan identity mismatch");
            if(state.ContainsKey("format_sha256"))throw new InvalidOperationException("Formatted revision already normalized; do not replay the earlier attachment ordering");
            var owned=ReadOwned(project,state);var attached=Dict(state["attachments"]);var ips=new Dictionary<string,InterruptionPoint>();
            foreach(Page pg in project.Pages)foreach(Placement pl in pg.AllPlacements){var ip=pl as InterruptionPoint;if(ip!=null)ips[Key(ip)]=ip;}
            var effective=new List<object>();var changes=new List<object>();
            // Read actual symbol-logic capacity. Never raise MaxConnectionCount
            // to silence the checker: reroot a branch onto a capable endpoint.
            foreach(object obj in (object[])plan["route_groups"])
            {
                var group=Dict(obj);var ends=(object[])group["ends"];int chosen=-1;
                for(int n=0;n<ends.Length;n++)
                {
                    var end=Dict(ends[n]);Function f=owned[S(end,"function_id")];int pin=Convert.ToInt32(end["pin_index"]);
                    if(f.Pins[pin].MaxConnectionCount>=ends.Length-1 && (chosen<0 || (f is Terminal && !(owned[S(Dict(ends[chosen]),"function_id")] is Terminal))))chosen=n;
                }
                if(chosen<0)throw new InvalidDataException("No endpoint has capacity for "+S(group,"name")+"; add a distribution terminal in a new reviewed circuit plan");
                var ordered=new List<object>();ordered.Add(ends[chosen]);for(int n=0;n<ends.Length;n++)if(n!=chosen)ordered.Add(ends[n]);
                effective.Add(new Dictionary<string,object>{{"name",S(group,"name")},{"net",S(group,"net")},{"potential",S(group,"potential")},{"ends",ordered.ToArray()}});
                changes.Add(new{group=S(group,"name"),source_index=chosen,required_connections=ends.Length-1,source_capacity=owned[S(Dict(ends[chosen]),"function_id")].Pins[Convert.ToInt32(Dict(ends[chosen])["pin_index"])].MaxConnectionCount});
            }
            project.LockAllObjects();
            for(int g=0;g<((object[])plan["route_groups"]).Length;g++)
            {
                var group=Dict(((object[])plan["route_groups"])[g]);var ends=(object[])group["ends"];var desired=Dict(((object[])Dict(effective[g])["ends"])[0]);
                InterruptionPoint source=null;int targetSort=101;
                for(int n=0;n<ends.Length;n++)
                {
                    string key=S(group,"name")+":"+n;string native=S(Dict(attached[key]),"native_key");
                    if(!ips.ContainsKey(native)||ips[native].VisibleName!=S(group,"name"))throw new InvalidDataException("Owned interruption changed: "+key);
                    var ip=ips[native];ip.IsStarSource=false;var end=Dict(ends[n]);
                    if(S(end,"function_id")==S(desired,"function_id")&&Convert.ToInt32(end["pin_index"])==Convert.ToInt32(desired["pin_index"]))source=ip;
                    else ip.Properties.INTERRUPTIONPOINT_SORT_CODE=targetSort++;
                }
                if(source==null)throw new InvalidDataException("Cannot resolve selected source");source.IsStarSource=true;
            }
            string canonical=null;foreach(object obj in (object[])plan["functions"]){var f=Dict(obj);if(S(f,"id")=="PLC1.BOX6")canonical=S(f,"description_zh");}
            if(canonical==null)throw new InvalidDataException("PLC canonical description missing");
            foreach(var f in owned.Values)if(f.SymbolVariant.SymbolName=="PLCC"&&f.VisibleName=="PLC1")f.Properties.FUNC_TEXT=Zh(canonical);
            state["effective_routes"]=effective.ToArray();Save(statePath,state);
            using(var gen=new Generate())gen.Connections(project,false);
            return new{routes=effective,capacity_selections=changes,max_connection_limits_changed=false,plc_box_text_synchronized=true};
        }
        static string Edge(Function a,int ai,Function b,int bi)
        {string x=Key(a)+":"+ai,y=Key(b)+":"+bi;return String.CompareOrdinal(x,y)<0?x+"|"+y:y+"|"+x;}
        static SortedSet<string> NativeEdges(Project project)
        {
            var result=new SortedSet<string>();foreach(Page pg in project.Pages)foreach(Function f in pg.Functions)foreach(Connection c in f.Connections)
            {
                var a=c.StartSymbolReference as Function;var b=c.EndSymbolReference as Function;
                if(a==null||b==null||!c.IsPlaced)throw new InvalidDataException("Unbound or unplaced native connection");
                result.Add(Edge(a,c.StartIndex,b,c.EndIndex));
            }
            return result;
        }
        static SortedSet<string> ExpectedEdges(object[] groups,Dictionary<string,Function> owned)
        {
            var edges=new SortedSet<string>();foreach(object obj in groups)
            {var ends=(object[])Dict(obj)["ends"];var a=Dict(ends[0]);for(int n=1;n<ends.Length;n++){var b=Dict(ends[n]);edges.Add(Edge(owned[S(a,"function_id")],Convert.ToInt32(a["pin_index"]),owned[S(b,"function_id")],Convert.ToInt32(b["pin_index"])));}}
            return edges;
        }
        static HashSet<string> OwnedTexts(Dictionary<string,object> plan)
        {
            var known=new HashSet<string>();foreach(var rows in Dict(plan["texts"]))foreach(object t in (object[])rows.Value)known.Add(S(Dict(t),"text"));
            foreach(object o in (object[])plan["functions"])
            {
                var f=Dict(o);string kind=S(f,"kind"),tag=S(f,"tag"),desc=S(f,"description_zh");
                known.Add(desc);known.Add(desc.Length>19?desc.Substring(0,19):desc);
                known.Add(tag+(kind=="terminal"?":"+S(f,"terminal"):""));
                if(f.ContainsKey("label_x")){string label=S(Dict(f["pin_labels"]),"0");known.Add(kind=="plc_channel"?S(f,"address")+"  "+label+"  "+S(f,"variable"):label);}
            }
            foreach(object g in (object[])plan["route_groups"])known.Add(S(Dict(g),"name"));
            return known;
        }
        static string ShortPin(Dictionary<string,object> spec,string index)
        {
            string role=S(Dict(spec["ports"]),index).Split(':')[1],label=S(Dict(spec["pin_labels"]),index);
            if(label.EndsWith("_TBD",StringComparison.Ordinal))
            {
                if(role.StartsWith("L1"))return "L1";if(role.StartsWith("L2"))return "L2";if(role.StartsWith("L3"))return "L3";if(role.StartsWith("N_"))return "N";
                if(role=="U"||role=="V"||role=="W"||role=="PE")return role;
                if(role=="A1"||role=="A2")return role+"?";
                if(role.Length>8)return role.Substring(0,7)+"?";return role+"?";
            }
            return label;
        }
        static void FormattedLabels(Function f,Dictionary<string,object> spec)
        {
            string kind=S(spec,"kind"),tag=S(spec,"tag");double x=Convert.ToDouble(spec["x"]),y=Convert.ToDouble(spec["y"]);
            if(spec.ContainsKey("no_caption"))return;
            if(kind=="box"||kind=="plc_box")
            {Text(f.Page,x+4,Convert.ToDouble(spec["y2"])-7,tag+(kind=="plc_box"?" CPU1212C":""),2.8);return;}
            if(spec.ContainsKey("label_x"))
            {
                string display=kind=="plc_channel"?S(spec,"address")+"  "+S(Dict(spec["pin_labels"]),"0")+"  "+S(spec,"variable"):S(Dict(spec["pin_labels"]),"0");
                Text(f.Page,Convert.ToDouble(spec["label_x"]),Convert.ToDouble(spec["label_y"]),display,2.5);
                if(kind=="plc_channel")Text(f.Page,Convert.ToDouble(spec["label_x"]),Convert.ToDouble(spec["label_y"])-5,S(spec,"description_zh"),2.2);
                return;
            }
            if(spec.ContainsKey("compact_caption"))
            {if(kind=="terminal")Text(f.Page,x+2,y+1,S(spec,"terminal"),2.2);return;}
            double lx=spec.ContainsKey("caption_x")?Convert.ToDouble(spec["caption_x"]):x+16;
            double ly=spec.ContainsKey("caption_y")?Convert.ToDouble(spec["caption_y"]):y+3;
            Text(f.Page,lx,ly,tag+(kind=="terminal"?":"+S(spec,"terminal"):""),2.8);
            string desc=S(spec,"description_zh");if(desc.Length>17)desc=desc.Substring(0,17);Text(f.Page,lx,ly-6,desc,2.3);
        }
        static object FormatDrawing(Project project,Dictionary<string,object> plan,string root,string hash,string formatHash)
        {
            string fmtPath=Rooted(root,"workstation-layout.json"),statePath=Rooted(root,"native-objects.json");
            if(String.IsNullOrEmpty(formatHash)||Hash(fmtPath)!=formatHash)throw new InvalidDataException("Reviewed formatting fingerprint mismatch");
            var fmt=Load(fmtPath);var state=Load(statePath);
            if(S(fmt,"schema_version")!="eplan-workstation-format-1"||S(fmt,"base_plan_sha256")!=hash||S(state,"plan_sha256")!=hash)throw new InvalidDataException("Formatting/base model mismatch");
            if(state.ContainsKey("format_sha256")){if(S(state,"format_sha256")==formatHash){ReadOwned(project,state);return new{already_formatted=true};}throw new InvalidDataException("Different formatted revision exists");}
            if(Hash(statePath)!=S(fmt,"baseline_state_sha256"))throw new InvalidDataException("Native baseline state changed since formatting was reviewed");
            var owned=ReadOwned(project,state);if(owned.Count!=Convert.ToInt32(fmt["expected_function_count"]))throw new InvalidDataException("Function inventory is incomplete");
            var oldGroups=(object[])state["effective_routes"];if(!NativeEdges(project).SetEquals(ExpectedEdges(oldGroups,owned)))throw new InvalidDataException("Native graph changed before formatting");
            var baseFunctions=new Dictionary<string,Dictionary<string,object>>();foreach(object o in (object[])plan["functions"])baseFunctions[S(Dict(o),"id")]=Dict(o);
            var specs=new Dictionary<string,Dictionary<string,object>>();foreach(object o in (object[])fmt["functions"])
            {
                var f=Dict(o);string id=S(f,"id");if(!baseFunctions.ContainsKey(id)||S(f,"tag")!=S(baseFunctions[id],"tag")||S(f,"symbol")!=S(baseFunctions[id],"symbol")||J().Serialize(f["ports"])!=J().Serialize(baseFunctions[id]["ports"]))throw new InvalidDataException("Formatting attempted to change electrical identity: "+id);
                double x=Convert.ToDouble(f["x"]),y=Convert.ToDouble(f["y"]);if(x<5||x>405||y<25||y>280)throw new InvalidDataException("Placement outside safe drawing bounds");specs[id]=f;
            }
            var groups=(object[])fmt["route_groups"];var originalMembers=new Dictionary<string,HashSet<string>>();
            foreach(object o in (object[])plan["route_groups"]){var g=Dict(o);var set=new HashSet<string>();foreach(object e in (object[])g["ends"])set.Add(S(Dict(e),"function_id")+":"+S(Dict(e),"pin_index"));originalMembers[S(g,"name")]=set;}
            foreach(object o in groups)
            {
                var g=Dict(o);var ends=(object[])g["ends"];var set=new HashSet<string>();foreach(object e in ends)set.Add(S(Dict(e),"function_id")+":"+S(Dict(e),"pin_index"));
                if(!originalMembers[S(g,"name")].SetEquals(set))throw new InvalidDataException("Formatting changed a conductor net");
                var source=Dict(ends[0]);var f=owned[S(source,"function_id")];int cap=f.Pins[Convert.ToInt32(source["pin_index"])].MaxConnectionCount;
                if(f.SymbolVariant.SymbolName=="PLCCP")cap=Math.Min(1,cap);if(cap<ends.Length-1)throw new InvalidDataException("Physical/logic source capacity is too small");
            }
            var known=OwnedTexts(plan);var textObjects=new List<DrawingText>();var ipObjects=new Dictionary<string,InterruptionPoint>();
            foreach(Page pg in project.Pages)foreach(Placement pl in pg.AllGraphicalPlacements)
            {var t=pl as DrawingText;if(t!=null){string value=t.Contents.GetString(ISOCode.Language.L_zh_CN);if(!known.Contains(value))throw new InvalidDataException("Unowned page text detected; preserve it: "+value);textObjects.Add(t);}}
            foreach(Page pg in project.Pages)foreach(Placement pl in pg.AllPlacements){var ip=pl as InterruptionPoint;if(ip!=null)ipObjects[Key(ip)]=ip;}
            var attached=Dict(state["attachments"]);if(attached.Count!=ipObjects.Count)throw new InvalidDataException("Unexpected interruption inventory");
            foreach(var item in attached)if(!ipObjects.ContainsKey(S(Dict(item.Value),"native_key")))throw new InvalidDataException("Owned interruption missing");
            Save(Rooted(root,"before-format-state.json"),state);project.LockAllObjects();
            foreach(var ip in ipObjects.Values)ip.Remove();foreach(var t in textObjects)t.Remove();
            foreach(var entry in specs)
            {
                var spec=entry.Value;var f=owned[entry.Key];if(S(spec,"kind")!="box"&&S(spec,"kind")!="plc_box")continue;
                f.SetLogicalArea(new PointD(Convert.ToDouble(spec["x"]),Convert.ToDouble(spec["y"])),new PointD(Convert.ToDouble(spec["x2"]),Convert.ToDouble(spec["y2"])));
            }
            foreach(var entry in specs)
            {
                var spec=entry.Value;var f=owned[entry.Key];
                if(f.SymbolVariant.VariantNr!=Convert.ToInt32(spec["variant"]))
                {
                    var potentials=new List<Pin.PotentialType>();var signals=new List<Pin.SignalType>();var externs=new List<bool>();foreach(Pin pin in f.Pins){potentials.Add(pin.Potential);signals.Add(pin.Signal);externs.Add(pin.IsExtern);}
                    f.SetSymbolVariant(Variant(project,spec),true);for(int n=0;n<potentials.Count&&n<f.Pins.Length;n++){f.Pins[n].Potential=potentials[n];f.Pins[n].Signal=signals[n];f.Pins[n].IsExtern=externs[n];}
                    foreach(var label in Dict(spec["pin_labels"]))f.Properties.FUNC_CONNECTIONDESIGNATION[Int32.Parse(label.Key)+1]=Convert.ToString(label.Value);
                }
                if(S(spec,"kind")!="box"&&S(spec,"kind")!="plc_box")f.Location=new PointD(Convert.ToDouble(spec["x"]),Convert.ToDouble(spec["y"]));
                HideProperties(f);FormattedLabels(f,spec);
                string kind=S(spec,"kind");
                if(kind=="function"&&f.SymbolVariant.SymbolName!="DCP")foreach(PinBase pin in f.GraphicalConnectionPoints)
                {
                    string label=ShortPin(spec,pin.Index.ToString());double px=f.Location.X+pin.Location.X,py=f.Location.Y+pin.Location.Y;string dir=pin.Direction.ToString();
                    Text(f.Page,px+(dir=="Left"?-8:3),py+(dir=="Up"?2:-3),label,2.0);
                }
                Dict(state["objects"])[entry.Key]=new Dictionary<string,object>{{"native_key",Key(f)},{"page",f.Page.IdentifyingName},{"symbol",f.SymbolVariant.SymbolName},{"x",f.Location.X},{"y",f.Location.Y}};
            }
            foreach(object o in (object[])fmt["new_pages"])
            {
                var pg=Dict(o);int n=Convert.ToInt32(pg["number"]);Page exists=null;foreach(Page candidate in project.Pages)if(candidate.IdentifyingName=="/"+n)exists=candidate;
                if(exists!=null)throw new InvalidDataException("Preserve existing additional graphics page");var props=new PagePropertyList();props.PAGE_COUNTER=n;var page=new Page();page.Create(project,DocumentTypeManager.DocumentType.Graphics,props);page.Properties.PAGE_NOMINATIOMN=Zh(S(pg,"name"));
            }
            var direct=new HashSet<string>();foreach(object o in (object[])fmt["direct_groups"])direct.Add(Convert.ToString(o));
            var nextAttached=new Dictionary<string,object>();
            foreach(object o in groups)
            {
                var g=Dict(o);var ends=(object[])g["ends"];
                if(direct.Contains(S(g,"name")))
                {
                    if(ends.Length!=2)throw new InvalidDataException("A direct group must have two endpoints");
                    continue; // face-to-face aligned symbol pins generate the actual native wire
                }
                for(int n=0;n<ends.Length;n++)
                {var e=Dict(ends[n]);string id=S(e,"function_id");int pin=Convert.ToInt32(e["pin_index"]);var ip=Attach(project,owned[id],pin,S(g,"name"),n==0,100+n,2.2);nextAttached[S(g,"name")+":"+n]=new{native_key=Key(ip),parent=id,pin_index=pin};}
            }
            foreach(var rows in Dict(fmt["texts"]))
            {
                Page pg=null;foreach(Page candidate in project.Pages)if(candidate.IdentifyingName=="/"+rows.Key)pg=candidate;if(pg==null)throw new InvalidDataException("Text page not created");
                foreach(object o in (object[])rows.Value){var t=Dict(o);Text(pg,Convert.ToDouble(t["x"]),Convert.ToDouble(t["y"]),S(t,"text"),Convert.ToDouble(t["height"]));}
            }
            foreach(object o in (object[])fmt["rectangles"])
            {
                var r=Dict(o);Page pg=null;foreach(Page candidate in project.Pages)if(candidate.IdentifyingName=="/"+S(r,"page"))pg=candidate;
                double x=Convert.ToDouble(r["x"]),y=Convert.ToDouble(r["y"]);var rect=new DrawingRectangle();rect.Create(pg);rect.SetArea(new PointD(x,y),new PointD(x+Convert.ToDouble(r["w"]),y+Convert.ToDouble(r["h"])));
                Text(pg,x+2,y+Convert.ToDouble(r["h"])-5,S(r,"label"),2.2);
            }
            project.Properties.PROJ_CREATORNAME1="AI-CAE Automation Lab";project.Properties.PROJ_CREATORNAME2="电气设计审查稿";project.Properties.PROJ_CREATORNAME3="";
            state["format_sha256"]=formatHash;state["effective_routes"]=groups;state["attachments"]=nextAttached;state["direct_groups"]=new List<string>(direct).ToArray();Save(statePath,state);
            using(var gen=new Generate())gen.Connections(project,false);
            var expected=ExpectedEdges(groups,owned);var actual=NativeEdges(project);bool match=expected.SetEquals(actual);
            return new{format_sha256=formatHash,native_functions=owned.Count,expected_edges=expected.Count,actual_edges=actual.Count,typed_edge_set_matches=match,direct_native_wire_groups=direct.Count,primitive_concept_pages=2,missing=Except(expected,actual),unexpected=Except(actual,expected),construction_release=false};
        }
        static object Except(SortedSet<string> a,SortedSet<string> b)
        {var list=new List<string>();foreach(string s in a)if(!b.Contains(s))list.Add(s);return list;}
        static object Polish(Project project,string root,string formatHash)
        {
            string statePath=Rooted(root,"native-objects.json"),fmtPath=Rooted(root,"workstation-layout.json");var state=Load(statePath);
            if(!state.ContainsKey("format_sha256")||S(state,"format_sha256")!=formatHash||Hash(fmtPath)!=formatHash)throw new InvalidDataException("A matching formatted revision is required");
            ReadOwned(project,state);var before=NativeEdges(project);
            if(state.ContainsKey("annotations_polished"))return RefineEngineeringNotes(project,root,state,statePath,before);
            var fmt=Load(fmtPath);project.LockAllObjects();int changed=0;
            foreach(object o in (object[])fmt["functions"])
            {
                var f=Dict(o);string kind=S(f,"kind");if(kind!="box"&&kind!="plc_box")continue;
                int number=Convert.ToInt32(f["page"]);Page page=null;foreach(Page pg in project.Pages)if(pg.IdentifyingName=="/"+number)page=pg;
                double x=Convert.ToDouble(f["x"]),y=Convert.ToDouble(f["y"]),x2=Convert.ToDouble(f["x2"]),y2=Convert.ToDouble(f["y2"]);
                string old=S(f,"tag")+(kind=="plc_box"?" CPU1212C":"");DrawingText found=null;
                foreach(Placement pl in page.AllGraphicalPlacements)
                {var t=pl as DrawingText;if(t!=null&&t.Contents.GetString(ISOCode.Language.L_zh_CN)==old&&Math.Abs(t.Location.X-(x+4))<.01&&Math.Abs(t.Location.Y-(y2-7))<.01){if(found!=null)throw new InvalidDataException("Ambiguous owned box caption");found=t;}}
                if(found==null)throw new InvalidDataException("Owned box caption is missing");
                if(kind=="plc_box")found.Location=new PointD(number==6?340:24,number==6?228:230);
                else
                {found.Remove();double cy=(y+y2)/2;Text(page,x+8,cy+4,S(f,"tag"),3.1);string desc=S(f,"description_zh");Text(page,x+8,cy-5,desc,2.4);}
                changed++;
            }
            foreach(Page pg in project.Pages)foreach(Placement pl in pg.AllGraphicalPlacements)
            {
                var t=pl as DrawingText;if(t==null)continue;string value=t.Contents.GetString(ISOCode.Language.L_zh_CN);
                if(value=="AC380/220V、DC24V｜N与PE分开｜未核脚号明确标TBD｜原生连线待回读校验")t.Contents=Zh("AC380/220V、DC24V｜N与PE分开｜未核脚号明确标TBD｜原生连接已按本修订回读");
                if(pg.IdentifyingName=="/6"&&value=="6ES7212-1AE40-0XB0；DI公共端1M")t.Location=new PointD(226,230);
                if(pg.IdentifyingName=="/7"&&value=="X12:1 3L+ / X12:2 3M；6DO")t.Location=new PointD(24,224);
            }
            foreach(Page pg in project.Pages)
            {
                if(pg.IdentifyingName=="/7")Text(pg,20,28,"箭头为原生中断点，同名N编号由真实Connection连接；接线去向见网络索引页。",2.2);
                if(pg.IdentifyingName=="/11")Text(pg,20,30,"X3:15、X3:16为已声明备用端子；没有目标的两项警告保留，不接虚假导线。",2.4);
            }
            if(!before.SetEquals(NativeEdges(project)))throw new InvalidOperationException("Annotation change altered the native edge set");
            state["annotations_polished"]=true;Save(statePath,state);
            return new{box_captions_corrected=changed,native_edges=before.Count,typed_edge_set_preserved=true,electrical_changes=false};
        }
        static object RefineEngineeringNotes(Project project,string root,Dictionary<string,object> state,string statePath,SortedSet<string> before)
        {
            if(state.ContainsKey("engineering_notes_refined"))return new{already_polished=true,native_edges=before.Count};
            var fmt=Load(Rooted(root,"workstation-layout.json"));var owned=ReadOwned(project,state);
            var words=new Dictionary<string,string>{{"KA1.NO1","VFD运行命令常开触点"},{"KA3.NO1","VFD故障复位常开触点"},{"KA2.NO1","气缸伸出阀控制触点"},{"R1.R","运行DI湿润负载"},{"R2.R","复位DI湿润负载"}};
            var texts=new Dictionary<string,DrawingText>();var specs=new Dictionary<string,Dictionary<string,object>>();
            foreach(object o in (object[])fmt["functions"])
            {
                var spec=Dict(o);string id=S(spec,"id");if(!words.ContainsKey(id))continue;specs[id]=spec;
                double x=Convert.ToDouble(spec["x"])+16,y=Convert.ToDouble(spec["y"])-3;string desc=S(spec,"description_zh");if(desc.Length>17)desc=desc.Substring(0,17);
                foreach(Placement pl in owned[id].Page.AllGraphicalPlacements)
                {var t=pl as DrawingText;if(t!=null&&t.Contents.GetString(ISOCode.Language.L_zh_CN)==desc&&Math.Abs(t.Location.X-x)<.01&&Math.Abs(t.Location.Y-y)<.01){if(texts.ContainsKey(id))throw new InvalidDataException("Ambiguous engineering caption");texts[id]=t;}}
            }
            if(texts.Count!=words.Count)throw new InvalidDataException("Expected electrical-function captions are missing; preserve changed text");
            project.LockAllObjects();foreach(var pair in words)
            {
                texts[pair.Key].Contents=Zh(pair.Value);owned[pair.Key].Properties.FUNC_TEXT=Zh(pair.Value);
                if(pair.Key.StartsWith("R",StringComparison.Ordinal)){var f=owned[pair.Key];Text(f.Page,f.Location.X+16,f.Location.Y-9,"1.8kΩ / 2W（候选，待核）",2.2);}
            }
            if(!before.SetEquals(NativeEdges(project)))throw new InvalidOperationException("Electrical-function annotations changed connectivity");
            state["engineering_notes_refined"]=true;Save(statePath,state);return new{electrical_function_captions_refined=words.Count,native_edges=before.Count,typed_edge_set_preserved=true};
        }
        static object ReopenedIdentity(Project project,string root,string baselineHash,bool bind)
        {
            string path=Rooted(root,"workstation-identity-baseline.json"),statePath=Rooted(root,"native-objects.json"),ownerPath=Rooted(root,"workstation-owner.json");
            if(String.IsNullOrEmpty(baselineHash)||Hash(path)!=baselineHash)throw new InvalidDataException("Native identity baseline hash mismatch");
            var baseline=Load(path);var state=Load(statePath);var owner=Load(ownerPath);var diffs=new List<string>();
            if(S(baseline,"model_sha256")!=S(owner,"model_sha256")||S(baseline,"format_sha256")!=S(state,"format_sha256"))throw new InvalidDataException("Baseline model/revision changed");
            if(state.ContainsKey("safety_revision")&&(!baseline.ContainsKey("safety_revision")||S(baseline,"safety_revision")!=S(state,"safety_revision")))throw new InvalidDataException("Reopened baseline must include current safety revision");
            if(state.ContainsKey("safety_notes_sha256")&&(!baseline.ContainsKey("safety_notes_sha256")||S(baseline,"safety_notes_sha256")!=S(state,"safety_notes_sha256")))throw new InvalidDataException("Reopened baseline must include current safety annotations");
            // Mutable state cannot establish its own route truth. Bind it back
            // to the reviewed plan hash already anchored in the baseline.
            string trustedRouteHash=state.ContainsKey("safety_revision")?S(baseline,"safety_revision"):S(baseline,"format_sha256");
            string trustedRoutePath=Rooted(root,state.ContainsKey("safety_revision")?"workstation-safety-R2.json":"workstation-layout.json");
            if(Hash(trustedRoutePath)!=trustedRouteHash)throw new InvalidDataException("Reviewed route anchor is missing or changed; never rebind from mutable state alone");
            var trustedRoutePlan=Load(trustedRoutePath);var trustedGroups=(object[])trustedRoutePlan["route_groups"];
            var trustedDirect=new HashSet<string>();foreach(object o in (object[])trustedRoutePlan["direct_groups"])trustedDirect.Add(Convert.ToString(o));
            var savedDirect=new HashSet<string>();foreach(object o in (object[])state["direct_groups"])savedDirect.Add(Convert.ToString(o));
            if(!trustedDirect.SetEquals(savedDirect))throw new InvalidDataException("Direct route manifest differs from reviewed plan");
            string guid=project.Properties.PROJ_GUID.ToString();if(owner.ContainsKey("project_guid")&&S(owner,"project_guid")!=guid)diffs.Add("Persistent project GUID changed");
            var native=new Dictionary<string,Function>();foreach(Page pg in project.Pages)foreach(Function f in pg.Functions)native[f.TypeIdentifier+":"+f.ObjectIdentifier]=f;
            var owned=new Dictionary<string,Function>();
            foreach(object obj in (object[])baseline["functions"])
            {
                var previous=Dict(obj);string old=S(previous,"native_key");string stable=old.Substring(old.IndexOf(':')+1),id=S(previous,"id");
                if(!native.ContainsKey(stable)){diffs.Add("Missing stable object: "+id);continue;}var f=native[stable];native.Remove(stable);owned[id]=f;
                if(f.Name!=S(previous,"name")||f.Page.IdentifyingName!=S(previous,"page")||f.SymbolVariant.SymbolName!=S(previous,"symbol")||Math.Abs(f.Location.X-Convert.ToDouble(previous["x"]))>.01||Math.Abs(f.Location.Y-Convert.ToDouble(previous["y"]))>.01)diffs.Add("Function geometry/name changed: "+id);
                if(f.IsMainFunction!=Convert.ToBoolean(previous["main"]))diffs.Add("Main function flag changed: "+id);
                if(previous.ContainsKey("symbol_variant")&&f.SymbolVariant.VariantNr!=Convert.ToInt32(previous["symbol_variant"]))diffs.Add("Symbol variant changed: "+id);
                if(f.Pins.Length!=((object[])previous["pins"]).Length)diffs.Add("Logical pin inventory changed: "+id);
                if(previous.ContainsKey("graphical_pins"))
                {
                    var expectedPins=(object[])previous["graphical_pins"];if(f.GraphicalConnectionPoints.Length!=expectedPins.Length)diffs.Add("Graphical pin inventory changed: "+id);
                    foreach(object o in expectedPins){var g=Dict(o);PinBase found=null;foreach(PinBase gp in f.GraphicalConnectionPoints)if(gp.Index==Convert.ToInt32(g["index"]))found=gp;if(found==null||Math.Abs(found.Location.X-Convert.ToDouble(g["x"]))>.01||Math.Abs(found.Location.Y-Convert.ToDouble(g["y"]))>.01||found.Direction.ToString()!=S(g,"direction"))diffs.Add("Graphical pin orientation changed: "+id);}
                }
                if(previous.ContainsKey("function_text")&&f.Properties.FUNC_TEXT.ToString(ISOCode.Language.L_zh_CN)!=S(previous,"function_text"))diffs.Add("Function description changed: "+id);
                if(previous.ContainsKey("contact_image"))
                {
                    var ci=f.ContactImage;var pc=previous["contact_image"];
                    if((ci==null)!=(pc==null))diffs.Add("Contact image inventory changed: "+id);
                    else if(ci!=null){var c=Dict(pc);if(Math.Abs(ci.Location.X-Convert.ToDouble(c["x"]))>.01||Math.Abs(ci.Location.Y-Convert.ToDouble(c["y"]))>.01||ci.AutoAlign!=Convert.ToBoolean(c["auto_align"])||ci.IsOnComponent!=Convert.ToBoolean(c["on_component"]))diffs.Add("Contact image placement changed: "+id);}
                }
                foreach(object po in (object[])previous["pins"])
                {
                    var pp=Dict(po);int index=Convert.ToInt32(pp["index"]);if(index>=f.Pins.Length){diffs.Add("Pin missing: "+id+":"+index);continue;}var pin=f.Pins[index];
                    if(pin.Signal.ToString()!=S(pp,"signal")||pin.Potential.ToString()!=S(pp,"potential")||f.Properties.FUNC_CONNECTIONDESIGNATION[index+1].ToString()!=S(pp,"displayed_designation"))diffs.Add("Pin semantics changed: "+id+":"+index);
                    if(pp.ContainsKey("max_connections")&&pin.MaxConnectionCount!=Convert.ToInt32(pp["max_connections"]))diffs.Add("Pin capacity changed: "+id+":"+index);
                    if(pp.ContainsKey("is_extern")&&pin.IsExtern!=Convert.ToBoolean(pp["is_extern"]))diffs.Add("Pin external flag changed: "+id+":"+index);
                }
                if(f.SymbolVariant.SymbolName=="PLCCP"&&(f.Properties.FUNC_PLCADDRESS.ToString()!=S(previous,"address")||f.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.ToString()!=S(previous,"variable")))diffs.Add("PLC address changed: "+id);
            }
            if(native.Count!=0)diffs.Add("Unexpected native functions: "+native.Count);
            if(baseline.ContainsKey("texts"))
            {
                var currentTexts=new Dictionary<string,DrawingText>();foreach(Page pg in project.Pages)foreach(Placement pl in pg.AllGraphicalPlacements){var t=pl as DrawingText;if(t!=null)currentTexts[t.TypeIdentifier+":"+t.ObjectIdentifier]=t;}
                foreach(object o in (object[])baseline["texts"]){var oldText=Dict(o);string key=S(oldText,"native_key"),stable=key.Substring(key.IndexOf(':')+1);if(!currentTexts.ContainsKey(stable)){diffs.Add("Missing stable text: "+stable);continue;}var t=currentTexts[stable];currentTexts.Remove(stable);if(t.Contents.GetString(ISOCode.Language.L_zh_CN)!=S(oldText,"text")||t.Page.IdentifyingName!=S(oldText,"page")||Math.Abs(t.Location.X-Convert.ToDouble(oldText["x"]))>.01||Math.Abs(t.Location.Y-Convert.ToDouble(oldText["y"]))>.01||(oldText.ContainsKey("height")&&Math.Abs(t.Height-Convert.ToDouble(oldText["height"]))>.01))diffs.Add("Drawing text changed: "+stable);}
                if(currentTexts.Count!=0)diffs.Add("Unexpected drawing text objects: "+currentTexts.Count);
            }
            var wantedPages=new HashSet<string>();foreach(object o in (object[])baseline["pages"])wantedPages.Add(S(Dict(o),"name"));var actualPages=new HashSet<string>();foreach(Page pg in project.Pages)actualPages.Add(pg.IdentifyingName);if(!wantedPages.SetEquals(actualPages))diffs.Add("Page set changed");
            if(diffs.Count==0)
            {
                var reviewed=ExpectedEdges(trustedGroups,owned);
                if(!reviewed.SetEquals(ExpectedEdges((object[])state["effective_routes"],owned)))diffs.Add("Mutable route state differs from reviewed plan");
                if(!NativeEdges(project).SetEquals(reviewed))diffs.Add("Full typed native edge set differs from reviewed plan");
            }
            var ips=new Dictionary<string,InterruptionPoint>();foreach(Page pg in project.Pages)foreach(Placement pl in pg.AllPlacements){var ip=pl as InterruptionPoint;if(ip!=null)ips[ip.TypeIdentifier+":"+ip.ObjectIdentifier]=ip;}
            var nextAttachments=new Dictionary<string,object>();
            var trustedAttachments=new Dictionary<string,Dictionary<string,object>>();
            foreach(object o in trustedGroups){var g=Dict(o);string name=S(g,"name");if(trustedDirect.Contains(name))continue;var ends=(object[])g["ends"];for(int n=0;n<ends.Length;n++)trustedAttachments[name+":"+n]=Dict(ends[n]);}
            if(trustedAttachments.Count!=Dict(state["attachments"]).Count)diffs.Add("Attachment inventory differs from reviewed route plan");
            foreach(var a in Dict(state["attachments"]))
            {
                var old=Dict(a.Value);string key=S(old,"native_key"),stable=key.Substring(key.IndexOf(':')+1);
                if(!ips.ContainsKey(stable)){diffs.Add("Missing interruption: "+a.Key);continue;}var ip=ips[stable];ips.Remove(stable);
                string group=a.Key.Substring(0,a.Key.LastIndexOf(':'));if(ip.VisibleName!=group)diffs.Add("Interruption name changed: "+a.Key);
                if(!trustedAttachments.ContainsKey(a.Key))diffs.Add("Unplanned interruption binding: "+a.Key);
                else
                {
                    var wanted=trustedAttachments[a.Key];string parent=S(wanted,"function_id");int pi=Convert.ToInt32(wanted["pin_index"]);
                    if(S(old,"parent")!=parent||Convert.ToInt32(old["pin_index"])!=pi)diffs.Add("Interruption parent differs from reviewed plan: "+a.Key);
                    if(owned.ContainsKey(parent))
                    {
                        var f=owned[parent];PinBase gp=null;foreach(PinBase candidate in f.GraphicalConnectionPoints)if(candidate.Index==pi)gp=candidate;
                        if(gp==null)diffs.Add("Interruption graphical pin missing: "+a.Key);
                        else
                        {
                            double x=f.Location.X+gp.Location.X,y=f.Location.Y+gp.Location.Y;string dir=gp.Direction.ToString();
                            if(dir=="Up")y+=12;else if(dir=="Down")y-=12;else if(dir=="Left")x-=12;else if(dir=="Right")x+=12;else diffs.Add("Unsupported interruption direction: "+a.Key);
                            int order=Int32.Parse(a.Key.Substring(a.Key.LastIndexOf(':')+1));
                            if(ip.Page!=f.Page||Math.Abs(ip.Location.X-x)>.01||Math.Abs(ip.Location.Y-y)>.01||ip.IsStarSource!=(order==0)||(order!=0&&ip.Properties.INTERRUPTIONPOINT_SORT_CODE.ToString()!=(100+order).ToString()))diffs.Add("Interruption geometry/source/order changed: "+a.Key);
                        }
                    }
                }
                nextAttachments[a.Key]=new{native_key=Key(ip),parent=S(old,"parent"),pin_index=Convert.ToInt32(old["pin_index"])};
            }
            if(ips.Count!=0)diffs.Add("Unexpected interruption inventory: "+ips.Count);
            if(bind)
            {
                if(diffs.Count!=0)throw new InvalidDataException("Cannot rebind a changed drawing: "+String.Join("; ",diffs.ToArray()));
                Save(Rooted(root,"before-rebind-owner.json"),owner);Save(Rooted(root,"before-rebind-state.json"),state);
                foreach(var item in owned)Dict(Dict(state["objects"])[item.Key])["native_key"]=Key(item.Value);
                state["attachments"]=nextAttachments;state["identity_baseline_sha256"]=baselineHash;owner["database_id"]=project.DatabaseIdentifier;owner["project_guid"]=guid;owner["last_bound_pid"]=Process.GetCurrentProcess().Id;owner["last_rebound_utc"]=DateTime.UtcNow.ToString("o");Save(ownerPath,owner);Save(statePath,state);
            }
            return new{matched=diffs.Count==0,differences=diffs,functions_checked=owned.Count,native_edges=NativeEdges(project).Count,pages_checked=actualPages.Count,project_guid=guid,database_id=project.DatabaseIdentifier,reviewed_route_sha256=trustedRouteHash,metadata_rebound=bind,native_drawing_modified=false};
        }
        static object ApplyPage(Project project,Dictionary<string,object> plan,string root,string hash,int number)
        {
            string statePath=Rooted(root,"native-objects.json");
            var state=File.Exists(statePath)?Load(statePath):new Dictionary<string,object>{{"plan_sha256",hash},{"objects",new Dictionary<string,object>()},{"completed_pages",new object[0]},{"attachments",new Dictionary<string,object>()}};
            if(S(state,"plan_sha256")!=hash)throw new InvalidDataException("Layout changed after native authoring started; inspect native state instead of replay");
            var owned=ReadOwned(project,state);var done=new HashSet<int>();foreach(object p in (object[])state["completed_pages"])done.Add(Convert.ToInt32(p));
            if(done.Contains(number))return new{already_applied=true,page=number,objects_verified=owned.Count};
            project.LockAllObjects();Page page=GetPage(project,number,plan);
            foreach(object p in (object[])plan["pages"])if(Convert.ToInt32(Dict(p)["number"])==number)page.Properties.PAGE_NOMINATIOMN=Zh(S(Dict(p),"name"));
            if(number==1)
            {
                var extras=new List<Page>();foreach(Page pg in project.Pages)if(pg.IdentifyingName=="=CA1+EAA/1"&&pg.Functions.Length==0)extras.Add(pg);
                foreach(Page pg in extras)pg.Remove();
            }
            foreach(object item in (object[])plan["functions"]){var spec=Dict(item);if(Convert.ToInt32(spec["page"])==number)EnsureFunction(project,plan,spec,state,owned,statePath);}
            var texts=Dict(plan["texts"]);if(texts.ContainsKey(number.ToString()))foreach(object obj in (object[])texts[number.ToString()])
            {var t=Dict(obj);Text(page,Convert.ToDouble(t["x"]),Convert.ToDouble(t["y"]),S(t,"text"),Convert.ToDouble(t["height"]));}
            var attached=Dict(state["attachments"]);
            foreach(object obj in (object[])plan["route_groups"])
            {
                var group=Dict(obj);var ends=(object[])group["ends"];
                if(ends.Length<2||ends.Length>3)throw new InvalidDataException("Native stars must have one source and at most two targets");
                for(int n=0;n<ends.Length;n++)
                {
                    var end=Dict(ends[n]);string id=S(end,"function_id");
                    if(!owned.ContainsKey(id)||owned[id].Page!=page)continue;
                    string attachment=S(group,"name")+":"+n;
                    if(attached.ContainsKey(attachment))continue;
                    var ip=Attach(project,owned[id],Convert.ToInt32(end["pin_index"]),S(group,"name"),n==0,100+n);
                    attached[attachment]=new{native_key=Key(ip),parent=id,pin_index=Convert.ToInt32(end["pin_index"])};Save(statePath,state);
                }
            }
            using(var generator=new Generate())generator.Connections(project,false);
            done.Add(number);state["completed_pages"]=new List<int>(done).ToArray();Save(statePath,state);
            return new{page=number,owned_functions=owned.Count,attachments=attached.Count,completed_pages=done.Count};
        }
        static object Snapshot(Project project,string root)
        {
            var functions=new List<object>();var edges=new Dictionary<string,object>();var roles=new Dictionary<string,object>();var interrupts=new List<object>();var texts=new List<object>();
            string statePath=Rooted(root,"native-objects.json");
            var ids=new Dictionary<string,string>();if(File.Exists(statePath))foreach(var row in Dict(Load(statePath)["objects"]))ids[S(Dict(row.Value),"native_key")]=row.Key;
            foreach(Page page in project.Pages)foreach(Function f in page.Functions)
            {
                string key=Key(f),id=ids.ContainsKey(key)?ids[key]:null;var pins=new List<object>();
                foreach(Pin pin in f.Pins)pins.Add(new{index=pin.Index,designation=pin.Designation,displayed_designation=f.Properties.FUNC_CONNECTIONDESIGNATION[pin.Index+1].ToString(),potential=pin.Potential.ToString(),signal=pin.Signal.ToString(),is_extern=pin.IsExtern,max_connections=pin.MaxConnectionCount});
                bool plcPoint=f.SymbolVariant!=null&&f.SymbolVariant.SymbolName=="PLCCP";
                var gps=new List<object>();foreach(PinBase gp in f.GraphicalConnectionPoints)gps.Add(new{index=gp.Index,x=gp.Location.X,y=gp.Location.Y,direction=gp.Direction.ToString()});
                var ci=f.ContactImage;
                functions.Add(new{id=id,native_key=key,page=page.IdentifyingName,name=f.Name,tag=f.VisibleName,main=f.IsMainFunction,function_text=f.Properties.FUNC_TEXT.ToString(ISOCode.Language.L_zh_CN),contact_image=ci==null?null:(object)new{x=ci.Location.X,y=ci.Location.Y,auto_align=ci.AutoAlign,on_component=ci.IsOnComponent},symbol=f.SymbolVariant==null?null:f.SymbolVariant.SymbolName,symbol_variant=f.SymbolVariant==null?-1:f.SymbolVariant.VariantNr,placed=f.IsPlaced,x=f.Location.X,y=f.Location.Y,pins=pins,graphical_pins=gps,graphical_connections=f.GraphicalConnections.Length,address=plcPoint?f.Properties.FUNC_PLCADDRESS.ToString():null,variable=plcPoint?f.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.ToString():null});
                foreach(Connection e in f.Connections)
                {
                    string a=e.StartSymbolReference==null?null:Key(e.StartSymbolReference),b=e.EndSymbolReference==null?null:Key(e.EndSymbolReference);
                    edges[Key(e)]=new{native_key=Key(e),from_id=a!=null&&ids.ContainsKey(a)?ids[a]:null,to_id=b!=null&&ids.ContainsKey(b)?ids[b]:null,from_native=a,to_native=b,from_pin=e.StartIndex,to_pin=e.EndIndex,placed=e.IsPlaced};
                }
            }
            foreach(Page page in project.Pages)foreach(Placement pl in page.AllPlacements)
            {var ip=pl as InterruptionPoint;if(ip!=null)interrupts.Add(new{native_key=Key(ip),name=ip.Name,visible=ip.VisibleName,page=page.IdentifyingName,x=ip.Location.X,y=ip.Location.Y,source=ip.IsStarSource,sort=ip.Properties.INTERRUPTIONPOINT_SORT_CODE.ToString(),graphical_connections=ip.GraphicalConnections.Length});}
            foreach(Page page in project.Pages)foreach(Placement pl in page.AllGraphicalPlacements)
            {var t=pl as DrawingText;if(t!=null)texts.Add(new{native_key=Key(t),page=page.IdentifyingName,x=t.Location.X,y=t.Location.Y,height=t.Height,text=t.Contents.GetString(ISOCode.Language.L_zh_CN)});}
            return new{functions=functions,connections=new List<object>(edges.Values),function_count=functions.Count,connection_count=edges.Count,interruptions=interrupts,texts=texts,source="live_native_this_call"};
        }
        static object ExportPdf(Project project,string root)
        {
            string output=Rooted(root,"Conveyor_Pusher_R1_native.pdf");var list=new List<Page>(project.Pages);
            list.Sort(delegate(Page a,Page b){int ai,bi;if(Int32.TryParse(a.IdentifyingName.TrimStart('/'),out ai)&&Int32.TryParse(b.IdentifyingName.TrimStart('/'),out bi))return ai.CompareTo(bi);return String.CompareOrdinal(a.IdentifyingName,b.IdentifyingName);});
            using(var exporter=new Export())exporter.PdfPages(new System.Collections.ArrayList(list),"EPLAN_default_value",output,Export.DegreeOfColor.BlackAndWhite,true,"",true);
            if(!File.Exists(output)||new FileInfo(output).Length==0)throw new IOException("Native PDF was not created");
            return new{pdf=output,bytes=new FileInfo(output).Length,pages=list.Count,source="EPLAN_PdfPages_API"};
        }
        static object MakeBackup(Project project,string root)
        {
            string target=project.ProjectLinkFilePath,dir=Rooted(root,"backups");Directory.CreateDirectory(dir);
            string name="Conveyor_Pusher_R1_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff")+".zw1";
            string file=Local(Path.Combine(dir,name));if(File.Exists(file))throw new IOException("Backup already exists; do not overwrite");
            using(var backup=new Backup())backup.Project(target,"Workstation native schematic review; not construction/commissioning release",dir,name,Backup.Type.MakeBackup,Backup.Medium.Disk,0.0,Backup.Amount.All,false,false,false,false);
            if(!File.Exists(file)||new FileInfo(file).Length==0)throw new IOException("Native backup file was not created");
            if(!File.Exists(target))throw new IOException("Original ELK is unexpectedly missing after backup; inspect before any more operations");
            return new{archive=file,bytes=new FileInfo(file).Length,sha256=Hash(file),method="MakeBackup",source_elk_exists=true,restore_test_performed=false};
        }
        static object CheckProject(Project project)
        {
            using(var check=new Check())check.VerifyProject(project,"",false);
            var collection=new PrjMessagesCollection(project);var messages=new List<object>();var en=collection.GetPrjMsgEnumerator();
            while(en.MoveNext())
            {
                var msg=en.Current as ProjectMessage;if(msg==null)continue;
                string name=null,page=null;var obj=msg.GetObject1() as Function;if(obj!=null){name=obj.Name;page=obj.Page==null?null:obj.Page.IdentifyingName;}
                if(messages.Count<2000)messages.Add(new{id=msg.GetId(),category=msg.GetCategory().ToString(),text=msg.GetText(),name=name,page=page});
            }
            return new{scheme="last_used_local",total=collection.Count,messages=messages,truncated=collection.Count>messages.Count};
        }
        static object Pages(Project p)
        {
            var rows=new List<object>();foreach(Page page in p.Pages)rows.Add(new {name=page.IdentifyingName,object_id=page.ObjectIdentifier,type_id=page.TypeIdentifier,functions=page.Functions.Length,width=page.Size.X,height=page.Size.Y,grid=page.GridSize});return rows;
        }
        static object Catalog(Project p)
        {
            var rows=new List<object>();
            foreach(string lib in new[]{"GB_symbol","SPECIAL"})
            {
            var library=new SymbolLibrary(p,lib);var available=new Dictionary<string,Symbol>();
            foreach(Symbol sy in library.Symbols)available[sy.Properties.SYMB_NAME.ToString()]=sy;
            var wanted=new HashSet<string>(lib=="SPECIAL"?new[]{"DC","DCP","BPIN","PLCCP","PLCC","TDEF"}:new[]{"K","S","O","SSA","SOA","M3","X","R","F1","F3","FA1","FA2","FA3","FA4","Q3","Q4","H","V1","V2"});
            if(lib=="GB_symbol")foreach(var pair in available)
            {
                string desc=pair.Value.Properties.SYMB_DESC.ToString().ToLowerInvariant();
                if(desc.Contains("fuse")||desc.Contains("diode")||desc.Contains("solenoid"))wanted.Add(pair.Key);
            }
            foreach(string name in wanted)
            {
                try
                {
                    if(!available.ContainsKey(name)){rows.Add(new{library=lib,symbol=name,unavailable=true});continue;}
                    var sy=available[name];var variants=new List<object>();
                    for(int n=0;n<8;n++)
                    {
                        try{var v=new SymbolVariant();v.Initialize(sy,n);var pins=new List<object>();foreach(var cp in v.ConnectionPoints)pins.Add(new{index=cp.Index,x=cp.Location.X,y=cp.Location.Y,direction=cp.Direction.ToString()});variants.Add(new{variant=n,pins=pins});}
                        catch(Exception ex){if(n==0)throw new InvalidOperationException("No variant 0: "+ex.Message);}
                    }
                    rows.Add(new{library=lib,symbol=name,description=sy.Properties.SYMB_DESC.ToString(),variants=variants});
                }
                catch(Exception ex){rows.Add(new{library=lib,symbol=name,error=ex.Message});}
            }
            }
            return rows;
        }
    }
}
