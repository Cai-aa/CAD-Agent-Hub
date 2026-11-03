using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Eplan.EplApi.ApplicationFramework;
using Eplan.EplApi.Base;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.DataModel.MasterData;
using Eplan.EplApi.DataModel.EObjects;
using Eplan.EplApi.HEServices;
using Eplan.EplApi.EServices;
using DrawingText = Eplan.EplApi.DataModel.Graphics.Text;
using DrawingRectangle = Eplan.EplApi.DataModel.Graphics.Rectangle;

namespace Codex.EplAddin
{
    // EPLAN objects are accessed only in callbacks marshalled to the OnInitGui thread.
    public sealed partial class CodexBridge : IEplAddIn
    {
        private const int MaxFrame = 4 * 1024 * 1024;
        private Control dispatcher;
        private Thread listener;
        private volatile bool stopping;
        private string pipeName;
        private string instanceId;
        private string discoveryPath;
        private int guiThread;
        private bool trialEnabled;

        public bool OnRegister(ref bool loadOnStart) { loadOnStart = true; return true; }
        public bool OnUnregister() { return true; }
        public bool OnInit() { return true; }

        public bool OnInitGui()
        {
            guiThread = Thread.CurrentThread.ManagedThreadId;
            trialEnabled = String.Equals(Environment.GetEnvironmentVariable("EPLAN_MCP_TRIAL_INSTANCE"), "1", StringComparison.Ordinal);
            dispatcher = new Control();
            dispatcher.CreateControl();
            instanceId = Guid.NewGuid().ToString("N");
            pipeName = "eplan-mcp-" + Process.GetCurrentProcess().Id + "-" + instanceId;
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EplanMcp", "instances");
            Directory.CreateDirectory(folder);
            discoveryPath = Path.Combine(folder, instanceId + ".json");
            var record = new Dictionary<string, object> {
                { "protocol", 1 }, { "instance_id", instanceId }, { "pid", Process.GetCurrentProcess().Id },
                { "build", NativeBuild() }, { "pipe", pipeName }, { "gui_thread", guiThread },
                { "start_filetime_utc", Process.GetCurrentProcess().StartTime.ToUniversalTime().ToFileTimeUtc().ToString() },
                { "trial_writes_enabled", trialEnabled },
                { "exe", Process.GetCurrentProcess().MainModule.FileName }
            };
            File.WriteAllText(discoveryPath, new JavaScriptSerializer().Serialize(record), new UTF8Encoding(false));
            listener = new Thread(Listen) { IsBackground = true, Name = "EplanMcpPipe" };
            listener.Start();
            return true;
        }

        public bool OnExit()
        {
            stopping = true;
            try { if (discoveryPath != null && File.Exists(discoveryPath)) File.Delete(discoveryPath); } catch { }
            try { dispatcher.Dispose(); } catch { }
            return true;
        }

        private void Listen()
        {
            while (!stopping)
            {
                try
                {
                    PipeSecurity acl = new PipeSecurity();
                    SecurityIdentifier sid = WindowsIdentity.GetCurrent().User;
                    acl.AddAccessRule(new PipeAccessRule(sid, PipeAccessRights.FullControl, AccessControlType.Allow));
                    using (var pipe = new NamedPipeServerStream(pipeName, PipeDirection.InOut, 1,
                        PipeTransmissionMode.Byte, PipeOptions.None, 8192, 8192, acl))
                    {
                        pipe.WaitForConnection();
                        if (stopping) break;
                        Dictionary<string, object> answer;
                        try
                        {
                            byte[] header = ReadExact(pipe, 4);
                            int size = BitConverter.ToInt32(header, 0);
                            if (size < 1 || size > MaxFrame) throw new InvalidDataException("Invalid frame length");
                            string json = new UTF8Encoding(false, true).GetString(ReadExact(pipe, size));
                            var obj = new JavaScriptSerializer().DeserializeObject(json) as Dictionary<string, object>;
                            if (obj == null) throw new InvalidDataException("Request must be object");
                            answer = Dispatch(obj);
                        }
                        catch (Exception ex)
                        {
                            answer = Error("INVALID_REQUEST", ex.Message);
                        }
                        byte[] output = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(answer));
                        if (output.Length <= MaxFrame)
                        {
                            byte[] prefix = BitConverter.GetBytes(output.Length);
                            pipe.Write(prefix, 0, prefix.Length);
                            pipe.Write(output, 0, output.Length);
                            pipe.Flush();
                        }
                    }
                }
                catch (Exception) { if (stopping) break; Thread.Sleep(200); }
            }
        }

        private Dictionary<string, object> Dispatch(Dictionary<string, object> obj)
        {
            if (!obj.ContainsKey("protocol") || Convert.ToInt32(obj["protocol"]) != 1 ||
                !obj.ContainsKey("instance_id") || Convert.ToString(obj["instance_id"]) != instanceId)
                return Error("INSTANCE_MISMATCH", "Protocol or instance mismatch");
            string op = obj.ContainsKey("operation") ? Convert.ToString(obj["operation"]) : "";
            if (op != "hello" && op != "list_projects" && op != "list_pages" &&
                op != "prepare_trial_pages" && op != "trial_place_motor" &&
                op != "list_functions" && op != "trial_symbol_catalog" &&
                op != "trial_place_relay_coils" && op != "trial_place_control_symbols" &&
                op != "trial_set_page_descriptions" && op != "trial_connect_interlocks" &&
                op != "trial_export_pdf" && op != "trial_route_interlocks" &&
                op != "trial_reconcile_interlocks" && op != "trial_asset_catalog" &&
                op != "trial_place_aux_devices" && op != "trial_place_control_boxes" &&
                op != "trial_place_plc_probe" && op != "trial_place_plc_channels" &&
                op != "trial_place_terminal_probe" && op != "trial_place_terminal_strips" &&
                op != "trial_plc_audit" && op != "trial_reconcile_plc_channels" &&
                op != "trial_place_plc_output_box" && op != "trial_terminal_audit" &&
                op != "trial_reconcile_terminals" && op != "trial_check_project" &&
                op != "trial_repair_definitions" && op != "trial_route_plc_outputs" &&
                op != "trial_route_aux_outputs" && op != "trial_spread_terminals" &&
                op != "trial_backup_project" && op != "trial_fix_ac_indicator" &&
                op != "trial_route_aux_services" && op != "trial_route_plc_inputs" && op != "trial_close_project" &&
                op != "trial_route_ac_input" && op != "trial_connection_catalog" && op != "trial_route_aux_feeds" &&
                op != "trial_route_ac_distribution" && op != "trial_place_ps1_interfaces" && op != "trial_route_dc_distribution" &&
                op != "trial_route_aux_neutral" && op != "trial_route_drive_power" &&
                op != "trial_route_protective_earth" && op != "trial_route_safety_channels" && op != "trial_add_review_pages" &&
                op != "trial_label_terminal_groups" && op != "trial_format_plc_chinese" && op != "trial_three_phase_catalog" && op != "trial_upgrade_three_phase" && op != "trial_reconcile_three_phase" && op != "trial_finalize_three_phase_order" && op != "trial_review_logic" && op != "trial_repair_basic_requirements" && op != "trial_reference_inspect" && op != "trial_reference_complete" && op != "trial_reference_reconcile" && op != "trial_reference_finalize" && op != "trial_reference_parameter_fix")
                if(op!="trial_client_engineering_inspect" && op!="trial_client_engineering_apply" && op!="trial_client_engineering_reconcile" && op!="trial_client_engineering_finalize" && op!="trial_curated_parts_inspect" && op!="trial_curated_parts_probe" && op!="trial_curated_parts_apply" && op!="trial_curated_parts_reconcile" && op!="trial_curated_parts_finalize")return Error("OPERATION_DISABLED", "Operation is not in the fixed allowlist");
            if ((op.StartsWith("trial_", StringComparison.Ordinal) || op == "prepare_trial_pages") && !trialEnabled)
                return Error("TRIAL_INSTANCE_REQUIRED", "Trial operations require a dedicated EPLAN process launch marker");
            var payload = obj.ContainsKey("payload") ? obj["payload"] as Dictionary<string, object> : null;
            // The GUI callback can finish after the pipe timeout. A task has no
            // disposable wait handle here, so a late completion cannot Set() an
            // already disposed event on EPLAN's GUI thread.
            var completion = new TaskCompletionSource<Dictionary<string, object>>();
            int executionState = 0; // queued=0, executing=1, cancelled before execution=2
            try
            {
                dispatcher.BeginInvoke((MethodInvoker)delegate {
                    if (Interlocked.CompareExchange(ref executionState, 1, 0) != 0)
                    {
                        completion.TrySetResult(Error("NATIVE_CANCELLED_BEFORE_EXECUTION", "Queued operation expired without execution"));
                        return;
                    }
                    try { completion.TrySetResult(ExecuteOnGui(op, payload)); }
                    catch (Exception ex) { completion.TrySetResult(Error("NATIVE_API_ERROR", ex.Message)); }
                });
            }
            catch (Exception ex) { return Error("DISPATCH_FAILED", ex.Message); }
            if (!completion.Task.Wait(TimeSpan.FromSeconds(60)))
            {
                if (Interlocked.CompareExchange(ref executionState, 2, 0) == 0)
                    return Error("NATIVE_QUEUE_TIMEOUT_NOT_EXECUTED", "Queued operation cancelled; no native API call began");
                stopping = true; // Unknown native state; reject later commands until reconciliation.
                try { if (discoveryPath != null && File.Exists(discoveryPath)) File.Delete(discoveryPath); } catch { }
                return Error("NATIVE_TIMEOUT_UNKNOWN", "GUI command did not complete before timeout");
            }
            return completion.Task.Result;
        }

        private Dictionary<string, object> ExecuteOnGui(string op, Dictionary<string, object> payload)
        {
            if (Thread.CurrentThread.ManagedThreadId != guiThread)
                return Error("WRONG_THREAD", "EPLAN API call was not on the captured GUI thread");
            if (op == "hello")
                return Ok(new Dictionary<string, object> { { "instance_id", instanceId },
                    { "pid", Process.GetCurrentProcess().Id }, { "build", NativeBuild() },
                    { "gui_thread", guiThread }, { "native_reads", true },
                    { "trial_writes_enabled", trialEnabled }, { "production_writes_enabled", false } });
            using (var locking = new LockingStep())
            using (var pm = new ProjectManager())
            {
                pm.LockProjectByDefault = false;
                Project[] projects = pm.OpenProjects;
                if(op=="trial_curated_parts_inspect")return InspectCuratedParts(pm,projects);
                if(op=="trial_curated_parts_finalize")return FinalizeCuratedDocument(pm,projects);
                if(op=="trial_curated_parts_probe")return ApplyCuratedParts(pm,projects,false,true);
                if(op=="trial_curated_parts_apply")return ApplyCuratedParts(pm,projects,false);
                if(op=="trial_curated_parts_reconcile")return ApplyCuratedParts(pm,projects,true);
                if(op=="trial_client_engineering_inspect")return InspectClientEngineering(pm,projects);
                if(op=="trial_client_engineering_apply")return ApplyClientEngineering(pm,projects,false);
                if(op=="trial_client_engineering_reconcile")return ApplyClientEngineering(pm,projects,true);
                if(op=="trial_client_engineering_finalize")return FinalizeClientDocument(pm,projects);
                if(trialEnabled && File.Exists(Path.Combine(ReferenceRoot,@"artifacts\client_engineering_A0_applied.json")) && (op.StartsWith("trial_")||op=="prepare_trial_pages") && op!="trial_export_pdf" && op!="trial_backup_project" && op!="trial_check_project" && op!="trial_close_project" && op!="trial_plc_audit" && op!="trial_terminal_audit")return Error("CLIENT_REVISION_OLD_MUTATION_DISABLED","Client engineering revision disables historical rewrites");
                if(op=="trial_three_phase_catalog")return ThreePhaseCatalog(pm,projects);
                if(op=="trial_upgrade_three_phase")return UpgradeTrialThreePhase(pm,projects);
                if(op=="trial_reconcile_three_phase")return ReconcileTrialThreePhase(pm,projects);
                if(op=="trial_finalize_three_phase_order")return FinalizeTrialPageOrder(pm,projects);
                if(op=="trial_review_logic")return ReviewTrialLogic(pm,projects);
                if(op=="trial_repair_basic_requirements")return RepairTrialBasicRequirements(pm,projects);
                if(op=="trial_reference_inspect")return InspectTrialReferenceInterfaces(pm,projects);
                if(op=="trial_reference_complete")return CompleteTrialReferenceInterfaces(pm,projects);
                if(op=="trial_reference_reconcile")return ReconcileTrialReferenceInterfaces(pm,projects);
                if(op=="trial_reference_finalize")return FinalizeTrialReferenceDrawing(pm,projects);
                if(op=="trial_reference_parameter_fix")return FixTrialMopParameters(pm,projects);
                if(trialEnabled && File.Exists(RuntimePath(@"artifacts\three_phase_applied.json")) &&
                    op.StartsWith("trial_") && op!="trial_export_pdf" && op!="trial_backup_project" && op!="trial_check_project" && op!="trial_close_project" && op!="trial_plc_audit" && op!="trial_terminal_audit" && op!="trial_symbol_catalog" && op!="trial_connection_catalog" && op!="trial_asset_catalog")
                    return Error("SUPERSEDED_SINGLE_PHASE_OPERATION","Three-phase revision exists; legacy placement mutation is disabled even when project is closed");
                foreach(Project current in (trialEnabled ? projects : new Project[0]))
                    if(String.Equals(current.ProjectLinkFilePath,RuntimePath(@"workspace\motor_forward_reverse_trial.elk"),StringComparison.OrdinalIgnoreCase) && FindTrialPage(current,"/16")!=null &&
                        op.StartsWith("trial_") && op!="trial_export_pdf" && op!="trial_backup_project" && op!="trial_check_project" && op!="trial_close_project" && op!="trial_plc_audit" && op!="trial_terminal_audit" && op!="trial_symbol_catalog" && op!="trial_connection_catalog" && op!="trial_asset_catalog")
                        return Error("SUPERSEDED_SINGLE_PHASE_OPERATION","Three-phase revision is active; legacy layout mutation is disabled");
                if (op == "trial_place_control_boxes" || op == "trial_place_plc_output_box" ||
                    op == "trial_place_plc_probe" || op == "trial_place_plc_channels" || op == "trial_reconcile_plc_channels" ||
                    op == "trial_route_plc_outputs" || op == "trial_route_aux_outputs" || op == "trial_route_dc_distribution")
                {
                    string layoutPath=RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
                    Project layoutProject=null;
                    foreach(Project current in (trialEnabled ? projects : new Project[0]))if(String.Equals(current.ProjectLinkFilePath,layoutPath,StringComparison.OrdinalIgnoreCase))layoutProject=current;
                    if(layoutProject==null && File.Exists(layoutPath))layoutProject=pm.OpenProject(layoutPath);
                    if(layoutProject!=null && ChineseLayoutActive(layoutProject))return FormatTrialPlcChinese(pm,pm.OpenProjects);
                }
                if (op == "prepare_trial_pages") return PrepareTrialPages(pm, projects);
                if (op == "trial_place_motor") return PlaceTrialMotor(pm, projects);
                if (op == "trial_place_relay_coils") return PlaceTrialRelayCoils(pm, projects);
                if (op == "trial_place_control_symbols") return PlaceTrialControlSymbols(pm, projects);
                if (op == "trial_set_page_descriptions") return SetTrialPageDescriptions(pm, projects);
                if (op == "trial_connect_interlocks") return ConnectTrialInterlocks(pm, projects);
                if (op == "trial_export_pdf") return ExportTrialPdf(pm, projects);
                if (op == "trial_route_interlocks") return RouteTrialInterlocks(pm, projects);
                if (op == "trial_reconcile_interlocks") return ReconcileTrialInterlocks(pm, projects);
                if (op == "trial_asset_catalog") return TrialAssetCatalog(pm, projects, payload);
                if (op == "trial_place_aux_devices") return PlaceTrialAuxDevices(pm, projects);
                if (op == "trial_place_control_boxes") return PlaceTrialControlBoxes(pm, projects);
                if (op == "trial_place_plc_probe") return PlaceTrialPlcChannels(pm, projects, false);
                if (op == "trial_place_plc_channels") return PlaceTrialPlcChannels(pm, projects, true);
                if (op == "trial_place_terminal_probe") return PlaceTrialTerminalStrips(pm, projects, false);
                if (op == "trial_place_terminal_strips") return PlaceTrialTerminalStrips(pm, projects, true);
                if (op == "trial_plc_audit") return AuditTrialPlc(pm, projects);
                if (op == "trial_reconcile_plc_channels") return ReconcileTrialPlcChannels(pm, projects);
                if (op == "trial_place_plc_output_box") return PlaceTrialPlcOutputBox(pm, projects);
                if (op == "trial_terminal_audit") return AuditTrialTerminals(pm, projects);
                if (op == "trial_reconcile_terminals") return ReconcileTrialTerminals(pm, projects);
                if (op == "trial_check_project") return CheckTrialProject(pm, projects);
                if (op == "trial_repair_definitions") return RepairTrialDefinitions(pm, projects);
                if (op == "trial_route_plc_outputs") return RouteTrialPlcOutputs(pm, projects);
                if (op == "trial_route_aux_outputs") return RouteTrialAuxOutputs(pm, projects);
                if (op == "trial_spread_terminals") return SpreadTrialTerminals(pm, projects);
                if (op == "trial_backup_project") return BackupTrialProject();
                if (op == "trial_fix_ac_indicator") return FixTrialAcIndicator(pm, projects);
                if (op == "trial_route_aux_services") return RouteTrialAuxServices(pm, projects);
                if (op == "trial_route_plc_inputs") return RouteTrialPlcInputs(pm, projects);
                if (op == "trial_close_project") return CloseTrialProject(pm, projects);
                if (op == "trial_route_ac_input") return RouteTrialAcInput(pm, projects);
                if (op == "trial_connection_catalog") return TrialConnectionCatalog(pm, projects);
                if (op == "trial_route_aux_feeds") return RouteTrialAuxFeeds(pm, projects);
                if (op == "trial_route_ac_distribution") return RouteTrialAcDistribution(pm, projects);
                if (op == "trial_place_ps1_interfaces") return PlaceTrialPs1Interfaces(pm, projects);
                if (op == "trial_route_dc_distribution") return RouteTrialDcDistribution(pm, projects);
                if (op == "trial_route_aux_neutral") return RouteTrialAuxNeutral(pm, projects);
                if (op == "trial_route_drive_power") return RouteTrialDrivePower(pm, projects);
                if (op == "trial_route_protective_earth") return RouteTrialProtectiveEarth(pm, projects);
                if (op == "trial_route_safety_channels") return RouteTrialSafetyChannels(pm, projects);
                if (op == "trial_add_review_pages") return AddTrialReviewPages(pm, projects);
                if (op == "trial_label_terminal_groups") return LabelTrialTerminalGroups(pm, projects);
                if (op == "trial_format_plc_chinese") return FormatTrialPlcChinese(pm, projects);
                if (op == "trial_symbol_catalog") return TrialSymbolCatalog(pm, projects);
                if (op == "list_projects")
                {
                    var names = new List<string>();
                    foreach (Project project in projects) names.Add(project.ProjectFullName);
                    return Ok(new Dictionary<string, object> { { "projects", names } });
                }
                string requested = payload != null && payload.ContainsKey("project_name") ? Convert.ToString(payload["project_name"]) : "";
                foreach (Project project in projects)
                {
                    if (!String.Equals(project.ProjectFullName, requested, StringComparison.OrdinalIgnoreCase)) continue;
                    if (op == "list_functions")
                    {
                        string requestedPage = payload != null && payload.ContainsKey("page_name") ? Convert.ToString(payload["page_name"]) : "";
                        foreach (Page page in project.Pages)
                        {
                            if (page.IdentifyingName != requestedPage) continue;
                            var functions = new List<Dictionary<string, object>>();
                            foreach (Function f in page.Functions)
                            {
                                var pinGeometry = new List<Dictionary<string, object>>();
                                var nativePins = new List<Dictionary<string, object>>();
                                var nativeEdges = new List<Dictionary<string, object>>();
                                Terminal terminal = f as Terminal;
                                foreach (PinBase pin in f.GraphicalConnectionPoints)
                                    pinGeometry.Add(new Dictionary<string, object> {
                                        { "index", pin.Index }, { "x", pin.Location.X },
                                        { "y", pin.Location.Y }, { "direction", pin.Direction.ToString() }
                                    });
                                foreach (Pin pin in f.Pins)
                                    nativePins.Add(new Dictionary<string, object> { { "index", pin.Index },
                                        { "designation", pin.Designation }, { "display_designation", f.Properties.FUNC_CONNECTIONDESIGNATION[pin.Index+1].ToString() }, { "type", pin.Type.ToString() }, { "potential", pin.Potential.ToString() },
                                        { "is_external", pin.IsExtern }, { "max_connections", pin.MaxConnectionCount }, { "signal", pin.Signal.ToString() } });
                                foreach (Connection edge in f.Connections)
                                    nativeEdges.Add(new Dictionary<string, object> {
                                        { "object_id", edge.ObjectIdentifier }, { "placed", edge.IsPlaced },
                                        { "type_id", edge.TypeIdentifier }, { "database_id", edge.DatabaseIdentifier },
                                        { "removable", edge.IsRemovable },
                                        { "start_index", edge.StartIndex }, { "end_index", edge.EndIndex },
                                        { "start_object_id", edge.StartSymbolReference == null ? 0 : edge.StartSymbolReference.ObjectIdentifier },
                                        { "end_object_id", edge.EndSymbolReference == null ? 0 : edge.EndSymbolReference.ObjectIdentifier },
                                        { "start_type_id", edge.StartSymbolReference == null ? 0 : edge.StartSymbolReference.TypeIdentifier },
                                        { "end_type_id", edge.EndSymbolReference == null ? 0 : edge.EndSymbolReference.TypeIdentifier },
                                        { "start", edge.StartSymbolReference == null ? null : ((Function)edge.StartSymbolReference).VisibleName },
                                        { "end", edge.EndSymbolReference == null ? null : ((Function)edge.EndSymbolReference).VisibleName }
                                    });
                                functions.Add(new Dictionary<string, object> {
                                    { "object_id", f.ObjectIdentifier },
                                    { "type_id", f.TypeIdentifier }, { "database_id", f.DatabaseIdentifier },
                                    { "name", f.Name }, { "visible_name", f.VisibleName },
                                    { "function_text_zh", f.Properties.FUNC_TEXT.IsEmpty ? "" : f.Properties.FUNC_TEXT.ToString(ISOCode.Language.L_zh_CN) },
                                    { "symbol_library", f.SymbolVariant == null ? null : f.SymbolVariant.SymbolLibraryName },
                                    { "symbol", f.SymbolVariant == null ? null : f.SymbolVariant.SymbolName },
                                    { "role_designation", f.SymbolVariant != null && (f.SymbolVariant.SymbolName == "DCP" || f.SymbolVariant.SymbolName == "S" || f.SymbolVariant.SymbolName == "SONOT1") &&
                                        !f.Properties.FUNC_CONNECTIONDESIGNATION[1].IsEmpty ? f.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString() : null },
                                    { "plc_address", terminal == null || f.SymbolVariant == null || f.SymbolVariant.SymbolName != "PLCCP" || terminal.Properties.FUNC_PLCADDRESS.IsEmpty ? null : terminal.Properties.FUNC_PLCADDRESS.ToString() },
                                    { "terminal_number", terminal == null || f.SymbolVariant == null || f.SymbolVariant.SymbolName != "X" || terminal.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty ? null : terminal.Properties.FUNC_PINORTERMINALNUMBER.ToString() },
                                    { "connection_points", f.GraphicalConnectionPoints.Length },
                                    { "native_connections", f.Connections.Length },
                                    { "graphical_connections", f.GraphicalConnections.Length },
                                    { "location", new Dictionary<string, object> { { "x", f.Location.X }, { "y", f.Location.Y } } },
                                    { "pin_geometry", pinGeometry }, { "native_pins", nativePins }, { "native_edges", nativeEdges }
                                });
                            }
                            var interruptionPoints = new List<Dictionary<string, object>>();
                            foreach (Placement placement in page.AllPlacements)
                            {
                                InterruptionPoint point = placement as InterruptionPoint;
                                if (point == null) continue;
                                interruptionPoints.Add(new Dictionary<string, object> { { "object_id", point.ObjectIdentifier },
                                    { "name", point.Name }, { "visible_name", point.VisibleName }, { "is_star_source", point.IsStarSource },
                                    { "sort_code", point.Properties.INTERRUPTIONPOINT_SORT_CODE.IsEmpty ? null : point.Properties.INTERRUPTIONPOINT_SORT_CODE.ToString() },
                                    { "variant", point.SymbolVariant.VariantNr }, { "graphical_connections", point.GraphicalConnections.Length } });
                            }
                            return Ok(new Dictionary<string, object> { { "project_name", requested },
                                { "page", requestedPage }, { "functions", functions }, { "interruption_points", interruptionPoints } });
                        }
                        return Error("PAGE_NOT_FOUND", "Explicit page not found");
                    }
                    var pages = new List<string>();
                    foreach (Page page in project.Pages) pages.Add(page.IdentifyingName);
                    return Ok(new Dictionary<string, object> { { "project_name", requested }, { "pages", pages } });
                }
                return Error("PROJECT_NOT_OPEN", "Explicit project is not open in this EPLAN instance");
            }
        }

        private Dictionary<string, object> LabelTrialTerminalGroups(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project project in projects)
                if (String.Equals(project.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = project;
            if (trial == null) return Error("TRIAL_NOT_OPEN", "Open the fixed trial before label verification");
            string[] tags = { "X1", "X2", "X2", "X2", "X3", "X4", "X4" };
            string[] numbers = { "1", "1", "2", "7", "1", "1", "3" };
            var terminals = new Terminal[tags.Length];
            var stripIds = new long[tags.Length];
            try
            {
                for (int i = 0; i < tags.Length; i++)
                {
                    terminals[i] = FindTrialTerminal(trial, tags[i], numbers[i]);
                    if (!terminals[i].Name.EndsWith("-" + tags[i] + ":" + numbers[i], StringComparison.Ordinal) ||
                        terminals[i].TerminalStrip == null || terminals[i].TerminalStrip.VisibleName != tags[i])
                        return Error("TERMINAL_LABEL_CONFLICT", "Terminal does not belong to the expected strip");
                    stripIds[i] = terminals[i].TerminalStrip.ObjectIdentifier;
                }
                trial.LockAllObjects();
                var labels = new List<string>();
                for (int i = 0; i < tags.Length; i++)
                {
                    terminals[i].VisibleName = tags[i];
                    if (terminals[i].TerminalStrip == null || terminals[i].TerminalStrip.ObjectIdentifier != stripIds[i] ||
                        !terminals[i].Name.EndsWith("-" + tags[i] + ":" + numbers[i], StringComparison.Ordinal))
                        return Error("PARTIAL_NATIVE_WRITE", "Explicit terminal DT changed its strip identity");
                    labels.Add(tags[i] + ":" + numbers[i]);
                }
                return Ok(new Dictionary<string, object> { { "explicit_group_labels", labels },
                    { "terminal_strip_identity_preserved", true }, { "new_electrical_connections", 0 } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static string FileSha256(string path)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(path))).Replace("-", "").ToLowerInvariant();
        }

        private static double ReviewNumber(Dictionary<string, object> command, string key, double minimum, double maximum)
        {
            double value = Convert.ToDouble(command[key], System.Globalization.CultureInfo.InvariantCulture);
            if (Double.IsNaN(value) || Double.IsInfinity(value) || value < minimum || value > maximum)
                throw new InvalidDataException("Review coordinate/size outside fixed drawing bounds");
            return value;
        }

        private Dictionary<string, object> AddTrialReviewPages(ProjectManager pm, Project[] projects)
        {
            string planPath = RuntimePath(@"artifacts\native_review_pages.plan.json");
            string modelPath = RuntimePath(@"artifacts\motor_forward_reverse.design.json");
            const string expectedHash = "d9304f00c9a81ed101f4ebd0bb1a4e3e4a8cb5224049074591cc9005b5660061";
            Dictionary<string, object> plan;
            object[] pagePlans;
            try
            {
                if (FileSha256(planPath) != expectedHash) return Error("REVIEW_PLAN_HASH_MISMATCH", "Review plan requires a tested bridge rebuild");
                plan = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(planPath, Encoding.UTF8)) as Dictionary<string, object>;
                if (plan == null || Convert.ToString(plan["schema"]) != "native-review-pages-1" ||
                    FileSha256(modelPath) != Convert.ToString(plan["model_sha256"]))
                    return Error("REVIEW_PLAN_STALE", "Model/plan identity mismatch");
                pagePlans = plan["pages"] as object[];
                if (pagePlans == null || pagePlans.Length != 7) throw new InvalidDataException("Unexpected review page count");
                var counters = new HashSet<int>();
                int total = 0;
                foreach (object item in pagePlans)
                {
                    var p = item as Dictionary<string, object>;
                    int number = Convert.ToInt32(p["number"]);
                    string type = Convert.ToString(p["type"]);
                    if (!counters.Add(number) || (number != 1 && number != 5 && number != 7 && (number < 10 || number > 13)))
                        throw new InvalidDataException("Page outside fixed review scope");
                    if ((number < 10 && type != "existing") || (number >= 10 && type != "Graphics" && type != "PanelLayout"))
                        throw new InvalidDataException("Review page type outside allowlist");
                    string title = Convert.ToString(p["title"]);
                    if (String.IsNullOrEmpty(title) || title.Length > 80) throw new InvalidDataException("Invalid review title");
                    object[] commands = p["commands"] as object[];
                    if (commands == null) throw new InvalidDataException("Invalid review commands");
                    total += commands.Length;
                    foreach (object value in commands)
                    {
                        var c = value as Dictionary<string, object>;
                        string kind = Convert.ToString(c["kind"]);
                        if (kind == "text")
                        {
                            ReviewNumber(c, "x", 10, 395); ReviewNumber(c, "y", 20, 270); ReviewNumber(c, "height", 1.5, 6);
                            if (Convert.ToString(c["text"]).Length > 200) throw new InvalidDataException("Review text too long");
                        }
                        else if (kind == "rect" && number >= 10)
                        {
                            double x1 = ReviewNumber(c, "x1", 10, 395), x2 = ReviewNumber(c, "x2", 10, 400);
                            double y1 = ReviewNumber(c, "y1", 20, 270), y2 = ReviewNumber(c, "y2", 20, 270);
                            if (x2 <= x1 || y2 <= y1) throw new InvalidDataException("Invalid review rectangle");
                        }
                        else throw new InvalidDataException("Only bounded text and mechanical/table rectangles are allowed");
                    }
                }
                if (total > 600) throw new InvalidDataException("Too many review commands");
            }
            catch (Exception ex) { return Error("REVIEW_PLAN_REJECTED", ex.Message); }

            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project project in projects)
                if (String.Equals(project.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = project;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            foreach (object item in pagePlans)
            {
                var p = (Dictionary<string, object>)item;
                int number = Convert.ToInt32(p["number"]);
                Page existing = FindTrialPage(trial, "/" + number.ToString());
                if (number < 10 && existing == null) return Error("PAGE_NOT_FOUND", "Existing review-note page missing");
                if (number >= 10 && existing != null)
                {
                    var expectedType = Convert.ToString(p["type"]) == "PanelLayout" ? DocumentTypeManager.DocumentType.PanelLayout : DocumentTypeManager.DocumentType.Graphics;
                    if (existing.PageType != expectedType || existing.Functions.Length != 0 ||
                        existing.Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN) != Convert.ToString(p["title"]))
                        return Error("REVIEW_PAGE_CONFLICT", "Existing page differs from fixed review plan");
                }
            }
            try
            {
                trial.LockAllObjects();
                int createdPages = 0, createdGraphics = 0, reusedGraphics = 0, removedEmptyTemplate = 0;
                foreach (object item in pagePlans)
                {
                    var p = (Dictionary<string, object>)item;
                    int number = Convert.ToInt32(p["number"]);
                    Page page = FindTrialPage(trial, "/" + number.ToString());
                    if (page == null)
                    {
                        var props = new PagePropertyList(); props.PAGE_COUNTER = number;
                        page = new Page();
                        page.Create(trial, Convert.ToString(p["type"]) == "PanelLayout" ? DocumentTypeManager.DocumentType.PanelLayout : DocumentTypeManager.DocumentType.Graphics, props);
                        var title = new MultiLangString(); title.AddString(ISOCode.Language.L_zh_CN, Convert.ToString(p["title"]));
                        page.Properties.PAGE_NOMINATIOMN = title;
                        createdPages++;
                    }
                    foreach (object value in (object[])p["commands"])
                    {
                        var c = (Dictionary<string, object>)value;
                        string kind = Convert.ToString(c["kind"]);
                        int found = 0;
                        if (kind == "text")
                        {
                            double x = ReviewNumber(c, "x", 10, 395), y = ReviewNumber(c, "y", 20, 270), height = ReviewNumber(c, "height", 1.5, 6);
                            string contents = Convert.ToString(c["text"]);
                            foreach (Placement placement in page.AllGraphicalPlacements)
                            {
                                DrawingText text = placement as DrawingText;
                                if (text != null && text.Contents.GetString(ISOCode.Language.L_zh_CN) == contents &&
                                    Math.Abs(text.Location.X - x) < 0.001 && Math.Abs(text.Location.Y - y) < 0.001 && Math.Abs(text.Height - height) < 0.001) found++;
                            }
                            if (found > 1) throw new InvalidOperationException("Duplicate review text");
                            if (found == 0)
                            {
                                var contentsMls = new MultiLangString(); contentsMls.AddString(ISOCode.Language.L_zh_CN, contents);
                                var text = new DrawingText(); text.Create(page, contentsMls, height); text.Location = new PointD(x, y);
                                createdGraphics++;
                            }
                            else reusedGraphics++;
                        }
                        else
                        {
                            double x1 = ReviewNumber(c, "x1", 10, 395), y1 = ReviewNumber(c, "y1", 20, 270),
                                   x2 = ReviewNumber(c, "x2", 10, 400), y2 = ReviewNumber(c, "y2", 20, 270);
                            foreach (Placement placement in page.AllGraphicalPlacements)
                            {
                                DrawingRectangle rectangle = placement as DrawingRectangle;
                                if (rectangle != null && Math.Abs(rectangle.LowerLeftCorner.X - x1) < 0.001 && Math.Abs(rectangle.LowerLeftCorner.Y - y1) < 0.001 &&
                                    Math.Abs(rectangle.UpperRightCorner.X - x2) < 0.001 && Math.Abs(rectangle.UpperRightCorner.Y - y2) < 0.001) found++;
                            }
                            if (found > 1) throw new InvalidOperationException("Duplicate review rectangle");
                            if (found == 0)
                            {
                                var rectangle = new DrawingRectangle(); rectangle.Create(page); rectangle.SetArea(new PointD(x1, y1), new PointD(x2, y2));
                                createdGraphics++;
                            }
                            else reusedGraphics++;
                        }
                    }
                }
                Page emptyTemplate = FindTrialPage(trial, "=CA1+EAA/1");
                if (emptyTemplate != null && emptyTemplate.Functions.Length == 0 && emptyTemplate.AllFirstLevelPlacements.Length == 0)
                {
                    emptyTemplate.Remove();
                    removedEmptyTemplate = 1;
                }
                return Ok(new Dictionary<string, object> { { "plan_sha256", expectedHash }, { "created_pages", createdPages },
                    { "created_graphics", createdGraphics }, { "reused_graphics", reusedGraphics },
                    { "removed_empty_owned_template_page", removedEmptyTemplate },
                    { "new_native_electrical_connections", 0 }, { "native_part_report_generated", false }, { "native_part_placements_created", 0 } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> CloseTrialProject(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            int found = 0;
            foreach (Project project in projects)
                if (String.Equals(project.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase))
                {
                    project.Close();
                    found++;
                }
            foreach (Project project in pm.OpenProjects)
                if (String.Equals(project.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase))
                    return Error("TRIAL_CLOSE_FAILED", "Trial project remains open");
            return Ok(new Dictionary<string, object> { { "trial_project_closed", true },
                { "closed_count", found }, { "other_projects_modified", false } });
        }

        private Dictionary<string, object> FixTrialAcIndicator(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page2 = FindTrialPage(trial, "/2");
            if (page2 == null) return Error("PAGE_NOT_FOUND", "/2");
            Function lamp = FindTrialFunction(page2, "HL1", "H");
            Function isolator = FindTrialFunction(page2, "QS1", "Q2");
            if (lamp == null || isolator == null) return Error("FUNCTION_NOT_FOUND", "HL1 or QS1 missing");
            if (isolator.Connections.Length != 0)
                return Error("AC_ALREADY_ROUTED", "Legacy unconnected-layout repair cannot run after AC input routing");
            try
            {
                trial.LockAllObjects();
                lamp.Location = new PointD(310.0, 75.0);
                using (var generator = new Generate()) generator.Connections(trial);
                if (lamp.Connections.Length != 0 || isolator.Connections.Length != 0)
                    return Error("UNEXPECTED_AC_CONNECTION", "HL1/QS1 still connected without a designed bus");
                return Ok(new Dictionary<string, object> { { "hl1", "unconnected_pending_AC_bus" },
                    { "qs1", "unconnected_pending_AC_distribution" }, { "unintended_connections", 0 } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> BackupTrialProject()
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            string targetDir = RuntimePath(@"artifacts");
            if (!File.Exists(trialPath)) return Error("TRIAL_NOT_FOUND", "Fixed trial project missing");
            Directory.CreateDirectory(targetDir);
            string archive = "motor_forward_reverse_trial_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss") + ".zw1";
            string fullPath = Path.Combine(targetDir, archive);
            if (File.Exists(fullPath)) return Error("ARCHIVE_EXISTS", "No backup overwrite");
            try
            {
                using (var backup = new Backup())
                    backup.Project(trialPath, "Codex MCP disposable trial, not production release",
                        targetDir, archive, Backup.Type.MakeBackup, Backup.Medium.Disk, 0.0,
                        Backup.Amount.All, false, false, false, false);
                if (!File.Exists(fullPath) || new FileInfo(fullPath).Length == 0)
                    return Error("BACKUP_FAILED", "Native backup did not create a nonempty archive");
                return Ok(new Dictionary<string, object> { { "archive", fullPath },
                    { "bytes", new FileInfo(fullPath).Length }, { "production_release", false } });
            }
            catch (Exception ex) { return Error("BACKUP_FAILED", ex.Message); }
        }

        private Dictionary<string, object> SpreadTrialTerminals(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page9 = FindTrialPage(trial, "/9");
            if (page9 == null) return Error("PAGE_NOT_FOUND", "/9");
            foreach (TerminalStrip existingStrip in page9.TerminalStrips)
                foreach (Terminal existingTerminal in existingStrip.Terminals)
                    if (existingTerminal.Connections.Length != 0)
                        return Error("ROUTED_TERMINALS_PRESENT", "Do not spread terminal placements after routing");
            string[] tags = { "X1", "X2", "X3", "X4" };
            int[] counts = { 3, 10, 4, 4 };
            try
            {
                trial.LockAllObjects();
                int globalIndex = 0;
                var chosen = new List<Terminal>();
                for (int s = 0; s < tags.Length; s++)
                {
                    TerminalStrip strip = null;
                    foreach (TerminalStrip candidate in page9.TerminalStrips)
                        if (candidate.VisibleName == tags[s]) strip = candidate;
                    if (strip == null) return Error("STRIP_NOT_FOUND", tags[s]);
                    for (int n = 1; n <= counts[s]; n++)
                    {
                        Terminal terminal = null;
                        foreach (Terminal t in strip.Terminals)
                            if (!t.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty &&
                                t.Properties.FUNC_PINORTERMINALNUMBER.ToString() == n.ToString())
                            {
                                if (terminal != null) return Error("TERMINAL_AMBIGUOUS", tags[s] + ":" + n.ToString());
                                terminal = t;
                            }
                        if (terminal == null) return Error("TERMINAL_MISSING", tags[s] + ":" + n.ToString());
                        terminal.Location = TerminalTrialLocation(globalIndex);
                        chosen.Add(terminal);
                        globalIndex++;
                    }
                }
                using (var generator = new Generate()) generator.Connections(trial);
                int connected = 0;
                foreach (Terminal t in chosen) connected += t.Connections.Length;
                if (connected != 0) return Error("UNEXPECTED_TERMINAL_CONNECTION", connected.ToString() + " terminal endpoints remain auto-connected");
                return Ok(new Dictionary<string, object> { { "terminals", chosen.Count },
                    { "native_terminal_connections", connected }, { "layout", "staggered_trial" } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static PointD TerminalTrialLocation(int index)
        {
            return new PointD(45.0 + index * 16.0, 250.0 - index * 8.5);
        }

        private Dictionary<string, object> RouteTrialAuxOutputs(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page7 = FindTrialPage(trial, "/7");
            if (page7 == null) return Error("PAGE_NOT_FOUND", "/7");
            string[] addresses = { "Q0.2", "Q0.3", "Q0.4", "Q0.5" };
            string[] tags = { "KA3", "HL3", "HL4", "HL5" };
            string[] symbols = { "K", "H", "H", "H" };
            double[] x = { 160.0, 200.0, 230.0, 260.0 };
            var outputs = new Terminal[4];
            var targets = new Function[4];
            for (int i = 0; i < 4; i++)
            {
                targets[i] = FindTrialFunction(page7, tags[i], symbols[i]);
                if (targets[i] == null) return Error("FUNCTION_NOT_FOUND", tags[i]);
                foreach (Function f in page7.Functions)
                {
                    Terminal t = f as Terminal;
                    if (t == null || t.SymbolVariant == null || t.SymbolVariant.SymbolName != "PLCCP" ||
                        t.Properties.FUNC_PLCADDRESS.IsEmpty || t.Properties.FUNC_PLCADDRESS.ToString() != addresses[i]) continue;
                    if (outputs[i] != null) return Error("PLC_ADDRESS_AMBIGUOUS", addresses[i]);
                    outputs[i] = t;
                }
                if (outputs[i] == null) return Error("PLC_ADDRESS_NOT_FOUND", addresses[i]);
            }
            try
            {
                trial.LockAllObjects();
                for (int i = 0; i < 4; i++) outputs[i].Location = new PointD(x[i], 80.0);
                using (var generator = new Generate()) generator.Connections(trial);
                var routed = new List<Dictionary<string, object>>();
                for (int i = 0; i < 4; i++)
                {
                    bool required = HasConnection(outputs[i], targets[i]);
                    if (!required || outputs[i].Connections.Length != 1 || outputs[i].GraphicalConnections.Length != 1)
                        return Error("ROUTE_MISMATCH", addresses[i] + " does not have exactly one required native route");
                    for (int j = 0; j < 4; j++)
                        if (j != i && HasConnection(outputs[i], targets[j]))
                            return Error("FORBIDDEN_CONNECTION", addresses[i] + " routes to " + tags[j]);
                    routed.Add(new Dictionary<string, object> { { "from", addresses[i] },
                        { "to", tags[i] }, { "native", true }, { "graphical", true } });
                }
                return Ok(new Dictionary<string, object> { { "routes", routed } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> RouteTrialPlcOutputs(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page7 = FindTrialPage(trial, "/7");
            if (page7 == null) return Error("PAGE_NOT_FOUND", "/7");
            Terminal q0 = null, q1 = null;
            foreach (Function f in page7.Functions)
            {
                Terminal t = f as Terminal;
                if (t == null || t.SymbolVariant == null || t.SymbolVariant.SymbolName != "PLCCP" ||
                    t.Properties.FUNC_PLCADDRESS.IsEmpty) continue;
                string address = t.Properties.FUNC_PLCADDRESS.ToString();
                if (address == "Q0.0") { if (q0 != null) return Error("PLC_ADDRESS_AMBIGUOUS", address); q0 = t; }
                if (address == "Q0.1") { if (q1 != null) return Error("PLC_ADDRESS_AMBIGUOUS", address); q1 = t; }
            }
            Function ka2NC = FindTrialFunction(page7, "KA2", "O");
            Function ka1NC = FindTrialFunction(page7, "KA1", "O");
            if (q0 == null || q1 == null || ka2NC == null || ka1NC == null)
                return Error("FUNCTION_NOT_FOUND", "PLC output or interlock contact missing");
            try
            {
                trial.LockAllObjects();
                q0.Location = new PointD(60.0, 40.0);
                q1.Location = new PointD(110.0, 40.0);
                using (var generator = new Generate()) generator.Connections(trial);
                bool first = HasConnection(q0, ka2NC);
                bool second = HasConnection(q1, ka1NC);
                bool forbidden = HasConnection(q0, ka1NC) || HasConnection(q1, ka2NC) || HasConnection(q0, q1);
                if (!first || !second || forbidden || q0.GraphicalConnections.Length != 1 || q1.GraphicalConnections.Length != 1)
                    return Error("ROUTE_MISMATCH", "Required PLC routes missing or forbidden route detected");
                return Ok(new Dictionary<string, object> { { "q0_0_to_ka2_nc", first },
                    { "q0_1_to_ka1_nc", second }, { "forbidden_connection", forbidden },
                    { "q0_0_native_count", q0.Connections.Length }, { "q0_1_native_count", q1.Connections.Length },
                    { "q0_0_graphical_count", q0.GraphicalConnections.Length },
                    { "q0_1_graphical_count", q1.GraphicalConnections.Length } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> RepairTrialDefinitions(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            try
            {
                trial.LockAllObjects();
                SymbolLibrary special = new SymbolLibrary(trial, "SPECIAL");
                Symbol blackSymbol = new Symbol(special, "DC");
                SymbolVariant blackVariant = new SymbolVariant();
                blackVariant.Initialize(blackSymbol, 0);
                var repaired = new List<string>();
                string[] pages = { "/3", "/4", "/5" };
                string[] tags = { "PS1", "VFD1", "SR1" };
                for (int i = 0; i < tags.Length; i++)
                {
                    Page page = FindTrialPage(trial, pages[i]);
                    BoxedDevice box = null;
                    foreach (BoxedDevice candidate in page.BoxedDevices)
                        if (candidate.VisibleName == tags[i]) box = candidate;
                    if (box == null) return Error("OBJECT_NOT_FOUND", tags[i]);
                    box.SetSymbolVariant(blackVariant, true);
                    repaired.Add(tags[i] + ":" + box.SymbolVariant.SymbolName);
                }
                Symbol stripSymbol = new Symbol(special, "TDEF");
                SymbolVariant stripVariant = new SymbolVariant();
                stripVariant.Initialize(stripSymbol, 0);
                Page page9 = FindTrialPage(trial, "/9");
                string[] strips = { "X1", "X2", "X3", "X4" };
                foreach (string tag in strips)
                {
                    TerminalStrip target = null;
                    foreach (TerminalStrip candidate in page9.TerminalStrips)
                        if (candidate.VisibleName == tag) target = candidate;
                    if (target == null) return Error("OBJECT_NOT_FOUND", tag);
                    target.SetSymbolVariant(stripVariant, true);
                    repaired.Add(tag + ":" + target.SymbolVariant.SymbolName);
                }
                Page page5 = FindTrialPage(trial, "/5");
                int stopCount = 0;
                foreach (Function f in page5.Functions)
                    if (f.VisibleName == "SB0" && f.SymbolVariant != null && f.SymbolVariant.SymbolName == "SONOT1")
                    {
                        stopCount++;
                        f.IsMainFunction = f.Location.X == 60.0;
                    }
                if (stopCount != 2) return Error("SB0_AMBIGUOUS", "Expected two emergency-stop contacts");
                return Ok(new Dictionary<string, object> { { "symbols", repaired },
                    { "sb0_main_function_count", 1 }, { "native_check_required", true } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> CheckTrialProject(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            try
            {
                trial.LockAllObjects();
                using (var check = new Check()) check.VerifyProject(trial, "", false);
                var collection = new PrjMessagesCollection(trial);
                var messages = new List<Dictionary<string, object>>();
                PrjMessagesEnumerator enumerator = collection.GetPrjMsgEnumerator();
                while (enumerator.MoveNext())
                {
                    ProjectMessage message = enumerator.Current as ProjectMessage;
                    if (message == null) continue;
                    if (messages.Count < 500)
                    {
                        string objectName = null, pageName = null;
                        try
                        {
                            StorableObject linked = message.GetObject1();
                            Function function = linked as Function;
                            Page page = linked as Page;
                            if (function != null)
                            {
                                objectName = function.Name;
                                pageName = function.Page == null ? null : function.Page.IdentifyingName;
                            }
                            else if (page != null) { objectName = page.IdentifyingName; pageName = page.IdentifyingName; }
                        }
                        catch (Exception) { }
                        messages.Add(new Dictionary<string, object> { { "id", message.GetId() },
                            { "category", message.GetCategory().ToString() },
                            { "text", message.GetText() }, { "object", objectName }, { "page", pageName } });
                    }
                }
                return Ok(new Dictionary<string, object> { { "message_count", collection.Count },
                    { "messages", messages }, { "truncated", collection.Count > messages.Count },
                    { "cleared_previous_trial_messages", false },
                    { "verification_scheme", "last_used_local" },
                    { "production_release_allowed", false } });
            }
            catch (Exception ex) { return Error("NATIVE_CHECK_FAILED", ex.Message); }
        }

        private Dictionary<string, object> ReconcileTrialTerminals(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page9 = FindTrialPage(trial, "/9");
            if (page9 == null) return Error("PAGE_NOT_FOUND", "/9");
            string[] tags = { "X1", "X2", "X3", "X4" };
            int[] counts = { 3, 10, 4, 4 };
            var duplicateObjects = new List<Terminal>();
            for (int s = 0; s < tags.Length; s++)
            {
                TerminalStrip strip = null;
                foreach (TerminalStrip candidate in page9.TerminalStrips)
                    if (candidate.VisibleName == tags[s])
                    {
                        if (strip != null) return Error("OBJECT_AMBIGUOUS", tags[s] + " strip duplicate");
                        strip = candidate;
                    }
                if (strip == null) return Error("STRIP_NOT_FOUND", tags[s]);
                for (int number = 1; number <= counts[s]; number++)
                {
                    var matches = new List<Terminal>();
                    foreach (Terminal t in strip.Terminals)
                        if (!t.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty &&
                            t.Properties.FUNC_PINORTERMINALNUMBER.ToString() == number.ToString()) matches.Add(t);
                    if (matches.Count == 0) return Error("TERMINAL_MISSING", tags[s] + ":" + number.ToString());
                    Terminal keep = matches[0];
                    foreach (Terminal t in matches)
                        if (t.ObjectIdentifier < keep.ObjectIdentifier) keep = t;
                    foreach (Terminal t in matches)
                    {
                        if (t == keep) continue;
                        if (t.Name != keep.Name || t.Location.X != keep.Location.X || t.Location.Y != keep.Location.Y ||
                            t.Page != page9 || t.SymbolVariant == null || t.SymbolVariant.SymbolName != "X" ||
                            t.Connections.Length != 0 || t.ArticleReferences.Length != 0)
                            return Error("DUPLICATE_DIFFERS", tags[s] + ":" + number.ToString());
                        duplicateObjects.Add(t);
                    }
                }
            }
            try
            {
                trial.LockAllObjects();
                int removed = 0;
                foreach (Terminal duplicate in duplicateObjects) { duplicate.Remove(); removed++; }
                int countAfter = 0;
                foreach (TerminalStrip strip in page9.TerminalStrips)
                    if (Array.IndexOf(tags, strip.VisibleName) >= 0) countAfter += strip.Terminals.Length;
                if (countAfter != 21) return Error("PARTIAL_NATIVE_WRITE", "Expected 21 native terminals after reconciliation");
                return Ok(new Dictionary<string, object> { { "removed_duplicates", removed },
                    { "terminal_count", countAfter }, { "strip_count", 4 } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> AuditTrialTerminals(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = false;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            var strips = new List<Dictionary<string, object>>();
            foreach (Page definitionPage in trial.Pages)
            foreach (TerminalStrip strip in definitionPage.TerminalStrips)
            {
                var rows = new List<Dictionary<string, object>>();
                foreach (Terminal t in strip.Terminals)
                    rows.Add(new Dictionary<string, object> { { "object_id", t.ObjectIdentifier },
                        { "number", t.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty ? null : t.Properties.FUNC_PINORTERMINALNUMBER.ToString() },
                        { "page", t.Page == null ? null : t.Page.IdentifyingName },
                        { "x", t.Location.X }, { "y", t.Location.Y },
                        { "symbol", t.SymbolVariant == null ? null : t.SymbolVariant.SymbolName },
                        { "connections", t.Connections.Length }, { "articles", t.ArticleReferences.Length },
                        { "name", t.Name }, { "visible_name", t.VisibleName } });
                strips.Add(new Dictionary<string, object> { { "strip", strip.VisibleName },
                    { "object_id", strip.ObjectIdentifier }, { "terminal_count", rows.Count },
                    { "terminals", rows } });
            }
            return Ok(new Dictionary<string, object> { { "strips", strips } });
        }

        private Dictionary<string, object> PlaceTrialPlcOutputBox(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page7 = FindTrialPage(trial, "/7");
            if (page7 == null) return Error("PAGE_NOT_FOUND", "/7");
            try
            {
                trial.LockAllObjects();
                PLC box = null;
                int found = 0;
                foreach (PLC p in page7.PLCs)
                    if (p.VisibleName == "PLC1") { box = p; found++; }
                if (found > 1) return Error("OBJECT_AMBIGUOUS", "Multiple PLC1 boxes on /7");
                if (box == null)
                {
                    SymbolLibrary lib = new SymbolLibrary(trial, "SPECIAL");
                    Symbol symbol = new Symbol(lib, "PLCC");
                    SymbolVariant variant = new SymbolVariant();
                    variant.Initialize(symbol, 0);
                    box = new PLC();
                    box.Create(page7, variant);
                    box.Name = "PLC1";
                    box.VisibleName = "PLC1";
                    box.IsMainFunction = false;
                }
                box.Location = new PointD(370.0, 240.0);
                var addresses = new List<string>();
                foreach (Terminal t in box.PLCTerminals)
                    if (!t.Properties.FUNC_PLCADDRESS.IsEmpty) addresses.Add(t.Properties.FUNC_PLCADDRESS.ToString());
                return Ok(new Dictionary<string, object> { { "page", "/7" }, { "tag", box.VisibleName },
                    { "is_main_function", box.IsMainFunction }, { "related_count", addresses.Count },
                    { "related_addresses", addresses } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> ReconcileTrialPlcChannels(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page7 = FindTrialPage(trial, "/7");
            if (page7 == null) return Error("PAGE_NOT_FOUND", "/7");
            string[] variables = { "CMD_FORWARD", "CMD_REVERSE", "CMD_VFD_RESET", "LAMP_FORWARD",
                "LAMP_REVERSE", "LAMP_FAULT", "SPARE_DO_1", "SPARE_DO_2" };
            var remove = new List<Terminal>();
            for (int i = 0; i < 8; i++)
            {
                string address = "Q0." + i.ToString();
                PointD desiredLocation = PlcTrialLocation(2 * i + 1);
                Terminal keeper = null;
                foreach (Function f in page7.Functions)
                {
                    Terminal t = f as Terminal;
                    if (t == null || t.SymbolVariant == null || t.SymbolVariant.SymbolName != "PLCCP" ||
                        t.Properties.FUNC_PLCADDRESS.IsEmpty || t.Properties.FUNC_PLCADDRESS.ToString() != address) continue;
                    bool desired = !t.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.IsEmpty &&
                        t.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.ToString() == variables[i] &&
                        Math.Abs(t.Location.X - desiredLocation.X) < 0.000001 &&
                        Math.Abs(t.Location.Y - desiredLocation.Y) < 0.000001;
                    if (desired)
                    {
                        if (keeper != null) return Error("OBJECT_AMBIGUOUS", address + " has multiple desired objects");
                        keeper = t;
                    }
                    else
                    {
                        if (t.Connections.Length != 0) return Error("OBJECT_HAS_CONNECTIONS", address + " duplicate is connected");
                        remove.Add(t);
                    }
                }
                if (keeper == null) return Error("KEEPER_NOT_FOUND", address + " desired object missing");
            }
            try
            {
                trial.LockAllObjects();
                int count = 0;
                foreach (Terminal duplicate in remove) { duplicate.Remove(); count++; }
                var addressCounts = new Dictionary<string, int>();
                foreach (Function f in page7.Functions)
                {
                    Terminal t = f as Terminal;
                    if (t == null || t.SymbolVariant == null || t.SymbolVariant.SymbolName != "PLCCP" ||
                        t.Properties.FUNC_PLCADDRESS.IsEmpty) continue;
                    string key = t.Properties.FUNC_PLCADDRESS.ToString();
                    addressCounts[key] = addressCounts.ContainsKey(key) ? addressCounts[key] + 1 : 1;
                }
                for (int i = 0; i < 8; i++)
                    if (!addressCounts.ContainsKey("Q0." + i.ToString()) || addressCounts["Q0." + i.ToString()] != 1)
                        return Error("PARTIAL_NATIVE_WRITE", "PLC output duplicates remain");
                return Ok(new Dictionary<string, object> { { "removed_duplicates", count },
                    { "unique_output_addresses", 8 } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> AuditTrialPlc(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = false;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            var plcBoxes = new List<Dictionary<string, object>>();
            foreach (Page plcPage in trial.Pages)
                foreach (PLC box in plcPage.PLCs)
                {
                    var related = new List<string>();
                    foreach (Terminal t in box.PLCTerminals)
                        related.Add(t.Properties.FUNC_PLCADDRESS.IsEmpty ? "EMPTY" : t.Properties.FUNC_PLCADDRESS.ToString());
                    plcBoxes.Add(new Dictionary<string, object> { { "page", plcPage.IdentifyingName },
                        { "name", box.VisibleName }, { "is_main_function", box.IsMainFunction },
                        { "object_id", box.ObjectIdentifier }, { "related_count", related.Count },
                        { "related_addresses", related } });
                }
            var rows = new List<Dictionary<string, object>>();
            foreach (Page p in trial.Pages)
                foreach (Function f in p.Functions)
                {
                    Terminal t = f as Terminal;
                    if (t == null || f.SymbolVariant == null || f.SymbolVariant.SymbolName != "PLCCP") continue;
                    string relatedName = null;
                    try { relatedName = t.PLC == null ? null : t.PLC.VisibleName; }
                    catch (Exception) { relatedName = "RELATION_ERROR"; }
                    rows.Add(new Dictionary<string, object> { { "page", p.IdentifyingName },
                        { "object_id", t.ObjectIdentifier },
                        { "x", t.Location.X }, { "y", t.Location.Y },
                        { "address", t.Properties.FUNC_PLCADDRESS.IsEmpty ? null : t.Properties.FUNC_PLCADDRESS.ToString() },
                        { "variable", t.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.IsEmpty ? null : t.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.ToString() },
                        { "plc_name", relatedName } });
                }
            return Ok(new Dictionary<string, object> { { "boxes", plcBoxes }, { "channels", rows } });
        }

        private Dictionary<string, object> PlaceTrialTerminalStrips(ProjectManager pm, Project[] projects, bool full)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page9 = FindTrialPage(trial, "/9");
            if (page9 == null) return Error("PAGE_NOT_FOUND", "/9");
            string[] tags = { "X1", "X2", "X3", "X4" };
            int[] counts = { 3, 10, 4, 4 };
            var strips = new TerminalStrip[tags.Length];
            var terminalsByNumber = new Dictionary<string, Terminal>[tags.Length];
            // Validate all fixed strip definitions and their terminals before any
            // mutation. Terminals can be placed on schematic pages other than /9.
            for (int i = 0; i < tags.Length; i++)
            {
                terminalsByNumber[i] = new Dictionary<string, Terminal>();
                foreach (Page scanPage in trial.Pages)
                    foreach (TerminalStrip candidate in scanPage.TerminalStrips)
                        if (candidate.VisibleName == tags[i])
                        {
                            if (strips[i] != null && strips[i].ObjectIdentifier != candidate.ObjectIdentifier)
                                return Error("STRIP_AMBIGUOUS", tags[i] + " has multiple definitions");
                            strips[i] = candidate;
                        }
                if (strips[i] == null) continue;
                if (strips[i].Page != page9)
                    return Error("STRIP_PAGE_CONFLICT", tags[i] + " definition is not on /9");
                foreach (Terminal terminal in strips[i].Terminals)
                {
                    if (terminal.SymbolVariant == null || terminal.SymbolVariant.SymbolName != "X" ||
                        terminal.SymbolVariant.SymbolLibraryName != "GB_symbol" || terminal.SymbolVariant.VariantNr != 0)
                        return Error("TERMINAL_SYMBOL_CONFLICT", tags[i] + " has an unexpected terminal symbol");
                    string number = terminal.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty ? "" :
                        terminal.Properties.FUNC_PINORTERMINALNUMBER.ToString();
                    int parsed;
                    if (!Int32.TryParse(number, out parsed) || parsed < 1 || parsed > counts[i] || number != parsed.ToString())
                        return Error("TERMINAL_NUMBER_CONFLICT", tags[i] + ":" + number);
                    if (terminalsByNumber[i].ContainsKey(number))
                        return Error("TERMINAL_AMBIGUOUS", tags[i] + ":" + number);
                    terminalsByNumber[i].Add(number, terminal);
                }
            }
            try
            {
                trial.LockAllObjects();
                SymbolLibrary library = new SymbolLibrary(trial, "GB_symbol");
                Symbol symbol = new Symbol(library, "X");
                SymbolVariant variant = new SymbolVariant();
                variant.Initialize(symbol, 0);
                var result = new List<Dictionary<string, object>>();
                int stripLimit = full ? 4 : 1;
                int globalIndex = 0;
                int createdStrips = 0, createdTerminals = 0;
                for (int stripIndex = 0; stripIndex < stripLimit; stripIndex++)
                {
                    TerminalStrip strip = strips[stripIndex];
                    if (strip == null)
                    {
                        strip = new TerminalStrip();
                        strip.Create(page9);
                        strip.Name = tags[stripIndex];
                        strip.VisibleName = tags[stripIndex];
                        strip.Location = new PointD(70.0 + stripIndex * 90.0, 255.0);
                        strips[stripIndex] = strip;
                        createdStrips++;
                    }
                    for (int n = 1; n <= counts[stripIndex]; n++)
                    {
                        Terminal found = null;
                        if (!terminalsByNumber[stripIndex].TryGetValue(n.ToString(), out found))
                        {
                            found = new Terminal();
                            found.Create(strip, page9, variant);
                            found.Properties.FUNC_PINORTERMINALNUMBER = n.ToString();
                            found.Location = TerminalTrialLocation(globalIndex);
                            terminalsByNumber[stripIndex].Add(n.ToString(), found);
                            createdTerminals++;
                        }
                        globalIndex++;
                        result.Add(new Dictionary<string, object> { { "strip", strip.VisibleName },
                            { "number", found.Properties.FUNC_PINORTERMINALNUMBER.ToString() },
                            { "placed", found.IsPlaced }, { "pin_count", found.Pins.Length },
                            { "page", found.Page == null ? null : found.Page.IdentifyingName } });
                    }
                    if (strip.Terminals.Length != counts[stripIndex])
                        return Error("PARTIAL_NATIVE_WRITE", "Unexpected terminal count after placement for " + tags[stripIndex]);
                }
                return Ok(new Dictionary<string, object> { { "terminals", result },
                    { "strip_count", stripLimit },
                    { "created_strips", createdStrips }, { "created_terminals", createdTerminals },
                    { "existing_placements_preserved", true },
                    { "electrical_connections_verified", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> PlaceTrialPlcChannels(ProjectManager pm, Project[] projects, bool full)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page diPage = FindTrialPage(trial, "/6");
            Page doPage = FindTrialPage(trial, "/7");
            if (diPage == null || doPage == null) return Error("PAGE_NOT_FOUND", "PLC trial pages missing");
            PLC plc = null;
            foreach (PLC candidate in diPage.PLCs)
                if (candidate.VisibleName == "PLC1") plc = candidate;
            if (plc == null) return Error("PLC_NOT_FOUND", "Native PLC1 box missing");
            try
            {
                trial.LockAllObjects();
                SymbolLibrary library = new SymbolLibrary(trial, "SPECIAL");
                Symbol symbol = new Symbol(library, "PLCCP");
                SymbolVariant variant = new SymbolVariant();
                variant.Initialize(symbol, 0);
                var result = new List<Dictionary<string, object>>();
                string[] diVariables = { "PB_FORWARD", "PB_STOP", "PB_REVERSE", "PB_RESET",
                    "SAFETY_OK", "VFD_READY", "VFD_FAULT", "SPARE_DI" };
                string[] doVariables = { "CMD_FORWARD", "CMD_REVERSE", "CMD_VFD_RESET", "LAMP_FORWARD",
                    "LAMP_REVERSE", "LAMP_FAULT", "SPARE_DO_1", "SPARE_DO_2" };
                var addresses = new List<string>();
                var variables = new List<string>();
                var pages = new List<Page>();
                int limit = full ? 8 : 1;
                for (int channel = 0; channel < limit; channel++)
                {
                    addresses.Add("I0." + channel.ToString()); variables.Add(diVariables[channel]); pages.Add(diPage);
                    addresses.Add("Q0." + channel.ToString()); variables.Add(doVariables[channel]); pages.Add(doPage);
                }
                for (int i = 0; i < addresses.Count; i++)
                {
                    Terminal found = null;
                    int matches = 0;
                    foreach (Page scanPage in new[] { diPage, doPage })
                        foreach (Function f in scanPage.Functions)
                        {
                            Terminal t = f as Terminal;
                            if (t == null || t.SymbolVariant == null || t.SymbolVariant.SymbolName != "PLCCP") continue;
                            if (!t.Properties.FUNC_PLCADDRESS.IsEmpty &&
                                t.Properties.FUNC_PLCADDRESS.ToString() == addresses[i]) { found = t; matches++; }
                        }
                    if (matches > 1) return Error("PLC_ADDRESS_AMBIGUOUS", addresses[i] + " appears more than once");
                    if (found == null)
                    {
                        Terminal terminal = new Terminal();
                        terminal.Create(plc, variant);
                        terminal.Name = "PLC1";
                        terminal.VisibleName = "PLC1";
                        terminal.Page = pages[i];
                        terminal.Location = PlcTrialLocation(i);
                        terminal.Properties.FUNC_PLCADDRESS = addresses[i];
                        terminal.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL = variables[i];
                        found = terminal;
                    }
                    else
                    {
                        string currentVariable = found.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.IsEmpty ? "" :
                            found.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.ToString();
                        if (!String.IsNullOrEmpty(currentVariable) && currentVariable != variables[i])
                            return Error("PLC_SYMBOL_CONFLICT", addresses[i] + " has another symbolic address");
                        if (String.IsNullOrEmpty(currentVariable))
                            found.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL = variables[i];
                    }
                    found.Location = PlcTrialLocation(i);
                    if (found.Properties.FUNC_PLCADDRESS.ToString() != addresses[i] ||
                        found.Properties.FUNC_PLCSYMBOLICADDRESS_MANUAL.ToString() != variables[i])
                        return Error("PARTIAL_NATIVE_WRITE", "PLC address/symbol readback mismatch " + addresses[i]);
                    result.Add(new Dictionary<string, object> { { "address", addresses[i] },
                        { "variable", variables[i] },
                        { "native_type", found.GetType().Name }, { "placed", found.IsPlaced },
                        { "page", found.Page == null ? null : found.Page.IdentifyingName },
                        { "pin_count", found.Pins.Length } });
                }
                return Ok(new Dictionary<string, object> { { "channels", result },
                    { "model", "SIEMENS_TBD" }, { "terminal_numbers_verified", false },
                    { "hardware_io_module_verified", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static PointD PlcTrialLocation(int index)
        {
            if (index % 2 == 0 && index < 8) return new PointD(50.0 + (index / 2) * 50.0, 100.0);
            if (index == 1) return new PointD(60.0, 40.0); // Q0.0
            if (index == 3) return new PointD(110.0, 40.0); // Q0.1
            if (index == 5) return new PointD(160.0, 80.0); // Q0.2
            if (index == 7) return new PointD(200.0, 80.0); // Q0.3
            if (index == 9) return new PointD(230.0, 80.0); // Q0.4
            if (index == 11) return new PointD(260.0, 80.0); // Q0.5
            return new PointD(index % 2 == 0 ? 220.0 : 315.0, 220.0 - (index / 2) * 20.0);
        }

        private Dictionary<string, object> PlaceTrialControlBoxes(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            try
            {
                trial.LockAllObjects();
                var summaries = new List<Dictionary<string, object>>();
                Page plcPage = FindTrialPage(trial, "/6");
                if (plcPage == null) return Error("PAGE_NOT_FOUND", "/6");
                PLC plc = null;
                foreach (PLC candidate in plcPage.PLCs)
                    if (candidate.VisibleName == "PLC1") plc = candidate;
                if (plc == null)
                {
                    SymbolLibrary library = new SymbolLibrary(trial, "SPECIAL");
                    Symbol symbol = new Symbol(library, "PLCC");
                    SymbolVariant variant = new SymbolVariant();
                    variant.Initialize(symbol, 0);
                    plc = new PLC();
                    plc.Create(plcPage, variant);
                    plc.Name = "PLC1";
                    plc.VisibleName = "PLC1";
                    plc.Location = new PointD(330.0, 240.0);
                }
                else
                    plc.Location = new PointD(330.0, 240.0);
                summaries.Add(new Dictionary<string, object> { { "page", "/6" }, { "tag", "PLC1" },
                    { "native_type", plc.GetType().Name }, { "model", "TBD" } });

                var boxes = new[] {
                    new TrialSpec("/3", "PS1", "DC", 150, 140, 1),
                    new TrialSpec("/4", "VFD1", "DC", 180, 150, 1),
                    new TrialSpec("/5", "SR1", "DC", 170, 145, 1)
                };
                foreach (TrialSpec spec in boxes)
                {
                    Page page = FindTrialPage(trial, spec.PageName);
                    if (page == null) return Error("PARTIAL_NATIVE_WRITE", "Missing page " + spec.PageName);
                    BoxedDevice box = null;
                    foreach (BoxedDevice existing in page.BoxedDevices)
                        if (existing.VisibleName == spec.Tag) box = existing;
                    if (box == null)
                    {
                        box = new BoxedDevice();
                        box.Create(page);
                        box.Name = spec.Tag;
                        box.VisibleName = spec.Tag;
                        box.Location = new PointD(spec.X, spec.Y);
                    }
                    summaries.Add(new Dictionary<string, object> { { "page", spec.PageName },
                        { "tag", spec.Tag }, { "native_type", box.GetType().Name },
                        { "model", "TBD" } });
                }
                return Ok(new Dictionary<string, object> { { "objects", summaries },
                    { "part_numbers_assigned", false }, { "physical_pins_verified", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static Page FindTrialPage(Project project, string name)
        {
            foreach (Page page in project.Pages) if (page.IdentifyingName == name) return page;
            return null;
        }

        private Dictionary<string, object> PlaceTrialAuxDevices(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            var specs = new[] {
                new TrialSpec("/2", "QS1", "Q2", 50, 120, 1),
                new TrialSpec("/2", "QF0", "FA2", 90, 120, 1),
                new TrialSpec("/2", "QF1", "FA2", 130, 120, 1),
                new TrialSpec("/2", "QF2", "FA2", 170, 120, 1),
                new TrialSpec("/2", "QF3", "FA1", 210, 120, 1),
                new TrialSpec("/2", "QF4", "FA1", 250, 120, 1),
                new TrialSpec("/2", "HL1", "H", 310, 75, 1),
                new TrialSpec("/3", "HL2", "H", 50, 100, 1),
                new TrialSpec("/7", "HL3", "H", 200, 120, 1),
                new TrialSpec("/7", "HL4", "H", 230, 120, 1),
                new TrialSpec("/7", "HL5", "H", 260, 120, 1),
                new TrialSpec("/3", "FU1", "FA1", 70, 210, 1),
                new TrialSpec("/3", "FU2", "FA1", 120, 210, 1),
                new TrialSpec("/3", "FU3", "FA1", 240, 210, 1),
                new TrialSpec("/5", "KM0", "K", 250, 90, 1),
                new TrialSpec("/8", "FAN1", "M2W_VE", 80, 110, 1),
                new TrialSpec("/8", "TS1", "SSM", 80, 160, 1),
                new TrialSpec("/8", "SQ1", "SSM", 180, 160, 1),
                new TrialSpec("/8", "EL1", "H", 180, 110, 1)
            };
            var result = new List<Dictionary<string, object>>();
            try
            {
                trial.LockAllObjects();
                SymbolLibrary library = new SymbolLibrary(trial, "GB_symbol");
                foreach (TrialSpec spec in specs)
                {
                    Page page = null;
                    foreach (Page p in trial.Pages) if (p.IdentifyingName == spec.PageName) page = p;
                    if (page == null) return Error("PARTIAL_NATIVE_WRITE", "Missing page " + spec.PageName);
                    int current = CountMatching(page, spec.Tag, spec.SymbolName);
                    if (current > 1) return Error("OBJECT_AMBIGUOUS", spec.Tag + " duplicates");
                    if (current == 0)
                    {
                        Symbol symbol = new Symbol(library, spec.SymbolName);
                        SymbolVariant variant = new SymbolVariant();
                        variant.Initialize(symbol, 0);
                        Function function = new Function();
                        function.Create(page, variant);
                        function.Name = spec.Tag;
                        function.VisibleName = spec.Tag;
                        function.Location = new PointD(spec.X, spec.Y);
                    }
                    if (CountMatching(page, spec.Tag, spec.SymbolName) != 1)
                        return Error("PARTIAL_NATIVE_WRITE", "Readback missing " + spec.Tag);
                    Function placed = FindTrialFunction(page, spec.Tag, spec.SymbolName);
                    if (placed.Connections.Length == 0) placed.Location = new PointD(spec.X, spec.Y);
                    result.Add(new Dictionary<string, object> { { "page", spec.PageName },
                        { "tag", spec.Tag }, { "symbol", spec.SymbolName } });
                }
                return Ok(new Dictionary<string, object> { { "placed_functions", result },
                    { "native_function_readback", true }, { "parts_assigned", false },
                    { "electrical_connections_verified", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static InterruptionPoint EnsureTrialInterruption(Project project, Page page, string name,
            int variantNumber, double x, double y, bool source, int sortCode = 0)
        {
            InterruptionPoint found = null;
            bool created = false;
            foreach (Placement placement in page.AllPlacements)
            {
                InterruptionPoint point = placement as InterruptionPoint;
                if (point == null || point.VisibleName != name) continue;
                if (sortCode != 0)
                {
                    bool matchingCode = !point.Properties.INTERRUPTIONPOINT_SORT_CODE.IsEmpty &&
                        point.Properties.INTERRUPTIONPOINT_SORT_CODE.ToString() == sortCode.ToString();
                    if (source ? (!point.IsStarSource && !matchingCode) : !matchingCode) continue;
                }
                if (found != null) throw new InvalidOperationException("Ambiguous interruption point " + name);
                found = point;
            }
            if (found == null)
            {
                SymbolLibrary library = new SymbolLibrary(project, "SPECIAL");
                Symbol symbol = new Symbol(library, "BPIN");
                SymbolVariant variant = new SymbolVariant();
                variant.Initialize(symbol, variantNumber);
                found = new InterruptionPoint();
                found.Create(page, variant);
                created = true;
                found.Name = name;
                found.VisibleName = name;
            }
            if (found.SymbolVariant.SymbolName != "BPIN" || found.SymbolVariant.VariantNr != variantNumber)
                throw new InvalidOperationException("Interruption variant conflict " + name);
            if (!created && (Math.Abs(found.Location.X - x) > 0.001 || Math.Abs(found.Location.Y - y) > 0.001))
                throw new InvalidOperationException("Interruption placement differs from fixed plan " + name);
            found.Location = new PointD(x, y);
            if (!source)
            {
                if (found.IsStarSource) found.IsStarSource = false;
                if (sortCode != 0) found.Properties.INTERRUPTIONPOINT_SORT_CODE = sortCode;
            }
            else found.IsStarSource = true;
            if (found.IsStarSource != source) throw new InvalidOperationException("Interruption star-source readback mismatch");
            return found;
        }

        private static InterruptionPoint AttachTrialInterruption(Project project, Function function, int index,
            string name, double distance, bool source, int sortCode)
        {
            PinBase selected = null;
            foreach (PinBase pin in function.GraphicalConnectionPoints) if (pin.Index == index) selected = pin;
            if (selected == null) throw new InvalidOperationException("Native graphical pin not found");
            double x = function.Location.X + selected.Location.X;
            double y = function.Location.Y + selected.Location.Y;
            int variant;
            switch (selected.Direction.ToString())
            {
                case "Up": y += distance; variant = 1; break;
                case "Down": y -= distance; variant = 3; break;
                case "Left": x -= distance; variant = 2; break;
                case "Right": x += distance; variant = 0; break;
                default: throw new InvalidOperationException("Unsupported native pin direction");
            }
            return EnsureTrialInterruption(project, function.Page, name, variant, x, y, source, sortCode);
        }

        private static Function EnsureTrialRolePoint(Project project, Page page, string tag, string role,
            int variantNumber, double x, double y)
        {
            Function found = null;
            bool created = false;
            foreach (Function function in page.Functions)
                if (function.SymbolVariant != null && function.SymbolVariant.SymbolName == "DCP" &&
                    (function.VisibleName == tag || function.Name.EndsWith("-" + tag + ":" + role, StringComparison.Ordinal)) &&
                    !function.Properties.FUNC_CONNECTIONDESIGNATION[1].IsEmpty &&
                    function.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString() == role)
                {
                    if (found != null) throw new InvalidOperationException("Ambiguous logical interface " + tag + ":" + role);
                    found = function;
                }
            if (found == null)
            {
                SymbolLibrary library = new SymbolLibrary(project, "SPECIAL");
                Symbol symbol = new Symbol(library, "DCP");
                SymbolVariant variant = new SymbolVariant();
                variant.Initialize(symbol, variantNumber);
                found = new Function();
                found.Create(page, variant);
                created = true;
                found.Name = tag;
                found.VisibleName = tag;
                found.IsMainFunction = false;
                found.Properties.FUNC_CONNECTIONDESIGNATION[1] = role;
                MultiLangString description = new MultiLangString();
                description.AddString(ISOCode.Language.L_zh_CN, "逻辑接口；实体端子 TBD");
                found.Properties.FUNC_TEXT = description;
            }
            if (found.SymbolVariant.VariantNr != variantNumber)
                throw new InvalidOperationException("Logical interface variant conflict " + role);
            if (!created &&
                (Math.Abs(found.Location.X - x) > 0.001 || Math.Abs(found.Location.Y - y) > 0.001))
                throw new InvalidOperationException("Logical interface placement differs from fixed plan " + role);
            found.Location = new PointD(x, y);
            return found;
        }

        private static Terminal FindTrialTerminal(Project project, string tag, string number)
        {
            Terminal found = null;
            foreach (Page page in project.Pages)
                foreach (TerminalStrip strip in page.TerminalStrips)
                    if (strip.VisibleName == tag)
                        foreach (Terminal terminal in strip.Terminals)
                            if (!terminal.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty &&
                                terminal.Properties.FUNC_PINORTERMINALNUMBER.ToString() == number)
                            {
                                if (found != null && found.ObjectIdentifier != terminal.ObjectIdentifier)
                                    throw new InvalidOperationException("Ambiguous terminal " + tag + ":" + number);
                                found = terminal;
                            }
            if (found == null) throw new InvalidOperationException("Missing terminal " + tag + ":" + number);
            return found;
        }

        private Dictionary<string, object> RouteTrialProtectiveEarth(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page2 = FindTrialPage(trial, "/2"), page3 = FindTrialPage(trial, "/3"),
                 page4 = FindTrialPage(trial, "/4"), page9 = FindTrialPage(trial, "/9");
            if (page2 == null || page3 == null || page4 == null || page9 == null) return Error("PAGE_NOT_FOUND", "PE pages");
            Function motor = FindTrialFunction(page4, "M1", "M3");
            Function qf0 = FindTrialFunction(page2, "QF0", "FA2");
            if (motor == null || qf0 == null || motor.Pins.Length != 4 || motor.Pins[3].Potential != Pin.PotentialType.PE)
                return Error("PE_PIN_UNVERIFIED", "Installed M3 symbol pin 3 is not verified as PE");
            try
            {
                Terminal incoming = FindTrialTerminal(trial, "X1", "3"), motorTerminal = FindTrialTerminal(trial, "X3", "4");
                trial.LockAllObjects();
                Function ps = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_PE_TBD", 1, 142, 130);
                Function drive = EnsureTrialRolePoint(trial, page4, "VFD1", "ROLE_PE_TBD", 1, 162, 160);
                Function cabinet = EnsureTrialRolePoint(trial, page9, "CABINET1", "ROLE_PE_TBD", 0, 300, 170);
                Function door = EnsureTrialRolePoint(trial, page9, "DOOR1", "ROLE_PE_TBD", 0, 300, 120);
                cabinet.IsMainFunction = true; door.IsMainFunction = true;
                incoming.Page = page2; incoming.Location = new PointD(90, 240);
                motorTerminal.Page = page4; motorTerminal.Location = new PointD(250, 80);
                foreach (Pin pin in incoming.Pins) pin.Potential = Pin.PotentialType.PE;
                foreach (Pin pin in motorTerminal.Pins) pin.Potential = Pin.PotentialType.PE;
                foreach (Function f in new[] { ps, drive, cabinet, door }) f.Pins[0].Potential = Pin.PotentialType.PE;
                AttachTrialInterruption(trial, incoming, 1, "PE", 20, true, 100);
                AttachTrialInterruption(trial, ps, 0, "PE", 20, false, 101);
                AttachTrialInterruption(trial, drive, 0, "PE", 20, false, 101);
                AttachTrialInterruption(trial, motorTerminal, 0, "PE", 20, false, 102);
                AttachTrialInterruption(trial, cabinet, 0, "PE", 20, false, 101);
                AttachTrialInterruption(trial, door, 0, "PE", 20, false, 102);
                AttachTrialInterruption(trial, motorTerminal, 1, "MOTOR_PE", 20, true, 100);
                AttachTrialInterruption(trial, motor, 3, "MOTOR_PE", 20, false, 101);
                using (var generator = new Generate()) generator.Connections(trial, false);
                foreach (Function f in new[] { ps, drive, cabinet, door })
                    if (!HasPinConnection(incoming, 1, f, 0) || HasPinConnection(qf0, 3, f, 0))
                        return Error("PE_ROUTE_MISMATCH", "PE target missing or mixed with N");
                if (!HasPinConnection(incoming, 1, motorTerminal, 0) || !HasPinConnection(motorTerminal, 1, motor, 3) ||
                    HasPinConnection(qf0, 3, motorTerminal, 0) || incoming.Connections.Length != 5)
                    return Error("PE_ROUTE_MISMATCH", "Motor PE or root membership mismatch");
                return Ok(new Dictionary<string, object> { { "placed_native_connections", 6 },
                    { "PE_separate_from_N_verified", true }, { "motor_symbol_PE_pin_verified", true },
                    { "PE_bus_hardware", "TBD; native logical PE network only" }, { "production_release", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> RouteTrialSafetyChannels(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page3 = FindTrialPage(trial, "/3"), page5 = FindTrialPage(trial, "/5");
            if (page3 == null || page5 == null) return Error("PAGE_NOT_FOUND", "Safety pages");
            BoxedDevice box = null;
            foreach (BoxedDevice candidate in page5.BoxedDevices) if (candidate.VisibleName == "SR1") box = candidate;
            Function km0 = FindTrialFunction(page5, "KM0", "K");
            Function fu2 = FindTrialFunction(page3, "FU2", "FA1"), fu3 = FindTrialFunction(page3, "FU3", "FA1");
            var contacts = new List<Function>();
            foreach (Function f in page5.Functions)
                if (f.VisibleName == "SB0" && f.SymbolVariant != null && f.SymbolVariant.SymbolName == "SONOT1") contacts.Add(f);
            contacts.Sort((a, b) => a.Location.X.CompareTo(b.Location.X));
            if (box == null || km0 == null || fu2 == null || fu3 == null || contacts.Count != 2)
                return Error("ENDPOINT_NOT_FOUND", "Safety fixed objects missing or ambiguous");
            for (int i = 0; i < 2; i++)
            {
                bool baseline = Math.Abs(contacts[i].Location.X - (i == 0 ? 60.0 : 100.0)) < 0.001 && Math.Abs(contacts[i].Location.Y - 80.0) < 0.001;
                bool planned = Math.Abs(contacts[i].Location.X - (i == 0 ? 50.0 : 100.0)) < 0.001 && Math.Abs(contacts[i].Location.Y - 190.0) < 0.001;
                if ((!baseline && !planned) || contacts[i].Pins.Length != 2)
                    return Error("SAFETY_LAYOUT_CONFLICT", "SB0 contact differs from fixed plan revisions");
            }
            try
            {
                Terminal[] outward = { FindTrialTerminal(trial, "X2", "7"), FindTrialTerminal(trial, "X2", "9") };
                Terminal[] inward = { FindTrialTerminal(trial, "X2", "8"), FindTrialTerminal(trial, "X2", "10") };
                trial.LockAllObjects();
                box.SetLogicalArea(new PointD(170, 90), new PointD(280, 250));
                Function[] sends = new Function[2], returns = new Function[2];
                for (int i = 0; i < 2; i++)
                {
                    string channel = i == 0 ? "A" : "B";
                    double x = i == 0 ? 50.0 : 100.0;
                    contacts[i].Location = new PointD(x, 190);
                    contacts[i].Properties.FUNC_CONNECTIONDESIGNATION[1] = "CH_" + channel + "_IN_TBD";
                    contacts[i].Properties.FUNC_CONNECTIONDESIGNATION[2] = "CH_" + channel + "_OUT_TBD";
                    outward[i].Page = page5; outward[i].Location = new PointD(x, 230);
                    inward[i].Page = page5; inward[i].Location = new PointD(x, 150);
                    sends[i] = EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_CH_" + channel + "_OUT_TBD", 1, 172, i == 0 ? 220 : 180);
                    returns[i] = EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_CH_" + channel + "_RETURN_TBD", 1, 172, i == 0 ? 200 : 160);
                    AttachTrialInterruption(trial, sends[i], 0, "ES" + channel, 20, true, 100);
                    AttachTrialInterruption(trial, outward[i], 0, "ES" + channel, 20, false, 101);
                    AttachTrialInterruption(trial, inward[i], 1, "ES" + channel + "_R", 20, true, 100);
                    AttachTrialInterruption(trial, returns[i], 0, "ES" + channel + "_R", 20, false, 101);
                }
                Function plus = EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_PWR_PLUS_TBD", 3, 278, 230);
                Function zero = EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_PWR_0V_TBD", 3, 278, 210);
                Function safeIn = EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_SAFE_IN_TBD", 3, 278, 190);
                Function safeOut = EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_SAFE_OUT_TBD", 3, 278, 170);
                EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_SAFE_RETURN_TBD", 3, 278, 150);
                EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_STATUS_TBD", 3, 278, 130);
                EnsureTrialRolePoint(trial, page5, "SR1", "ROLE_EDM_TBD", 3, 278, 110);
                Function psZero = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_0V_TBD", 3, 228, 130);
                km0.Location = new PointD(335, 110);
                km0.Properties.FUNC_CONNECTIONDESIGNATION[1] = "A1_TBD";
                km0.Properties.FUNC_CONNECTIONDESIGNATION[2] = "A2_TBD";
                AttachTrialInterruption(trial, plus, 0, "INPUT24", 20, false, 102);
                AttachTrialInterruption(trial, zero, 0, "DC0", 20, false, 301);
                AttachTrialInterruption(trial, safeIn, 0, "OUTPUT24", 20, false, 102);
                AttachTrialInterruption(trial, safeOut, 0, "SAFE_PERMIT", 20, true, 100);
                AttachTrialInterruption(trial, km0, 0, "SAFE_PERMIT", 20, false, 101);
                using (var generator = new Generate()) generator.Connections(trial, false);
                for (int i = 0; i < 2; i++)
                    if (!HasPinConnection(sends[i], 0, outward[i], 0) || !HasPinConnection(outward[i], 1, contacts[i], 0) ||
                        !HasPinConnection(contacts[i], 1, inward[i], 0) || !HasPinConnection(inward[i], 1, returns[i], 0) ||
                        HasConnection(sends[i], outward[1 - i]) || HasConnection(inward[i], returns[1 - i]))
                        return Error("ROUTE_MISMATCH", "Emergency-stop channel mapping mismatch");
                if (!HasPinConnection(fu2, 1, plus, 0) || !HasPinConnection(psZero, 0, zero, 0) ||
                    !HasPinConnection(fu3, 1, safeIn, 0) || !HasPinConnection(safeOut, 0, km0, 0))
                    return Error("ROUTE_MISMATCH", "Safety role supply/permit mapping mismatch");
                return Ok(new Dictionary<string, object> { { "placed_native_connections", 12 },
                    { "dual_channel_mapping_verified", true }, { "safety_circuit_complete", false },
                    { "unresolved_interfaces", new[] { "EDM loop", "STATUS common", "manual RESET", "safe output return" } },
                    { "physical_safety_terminals_verified", false }, { "production_release", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static Function EnsureTrialPowerContact(Project project, Page page, string inputRole, string outputRole,
            double x, double y)
        {
            Function found = null;
            foreach (Function function in page.Functions)
                if (function.VisibleName == "KM0" && function.SymbolVariant != null && function.SymbolVariant.SymbolName == "S" &&
                    !function.Properties.FUNC_CONNECTIONDESIGNATION[1].IsEmpty &&
                    function.Properties.FUNC_CONNECTIONDESIGNATION[1].ToString() == inputRole)
                {
                    if (found != null) throw new InvalidOperationException("Ambiguous KM0 power contact");
                    found = function;
                }
            if (found == null)
            {
                SymbolLibrary library = new SymbolLibrary(project, "GB_symbol");
                Symbol symbol = new Symbol(library, "S");
                SymbolVariant variant = new SymbolVariant();
                variant.Initialize(symbol, 0);
                found = new Function(); found.Create(page, variant);
                found.Name = "KM0"; found.VisibleName = "KM0"; found.IsMainFunction = false;
                found.Properties.FUNC_CONNECTIONDESIGNATION[1] = inputRole;
                found.Properties.FUNC_CONNECTIONDESIGNATION[2] = outputRole;
                found.Location = new PointD(x, y);
            }
            if (Math.Abs(found.Location.X - x) > 0.001 || Math.Abs(found.Location.Y - y) > 0.001 ||
                found.Properties.FUNC_CONNECTIONDESIGNATION[2].ToString() != outputRole)
                throw new InvalidOperationException("KM0 power contact differs from fixed draft plan");
            return found;
        }

        private Dictionary<string, object> RouteTrialDrivePower(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page2 = FindTrialPage(trial, "/2"), page4 = FindTrialPage(trial, "/4");
            if (page2 == null || page4 == null) return Error("PAGE_NOT_FOUND", "Drive power pages");
            Function qf1 = FindTrialFunction(page2, "QF1", "FA2"), motor = FindTrialFunction(page4, "M1", "M3");
            BoxedDevice box = null;
            foreach (BoxedDevice candidate in page4.BoxedDevices) if (candidate.VisibleName == "VFD1") box = candidate;
            if (qf1 == null || motor == null || box == null || motor.Pins.Length != 4)
                return Error("PIN_MAP_UNVERIFIED", "Drive endpoints or 4-pin motor symbol unavailable");
            try
            {
                Terminal[] terminals = new Terminal[3];
                for (int i = 0; i < 3; i++) terminals[i] = FindTrialTerminal(trial, "X3", (i + 1).ToString());
                trial.LockAllObjects();
                box.SetLogicalArea(new PointD(160, 120), new PointD(300, 235));
                Function lContact = EnsureTrialPowerContact(trial, page4, "L_IN_TBD", "L_OUT_TBD", 50, 210);
                Function nContact = EnsureTrialPowerContact(trial, page4, "N_IN_TBD", "N_OUT_TBD", 90, 210);
                Function l = EnsureTrialRolePoint(trial, page4, "VFD1", "ROLE_L_TBD", 0, 180, 232);
                Function n = EnsureTrialRolePoint(trial, page4, "VFD1", "ROLE_N_TBD", 0, 220, 232);
                EnsureTrialRolePoint(trial, page4, "VFD1", "ROLE_PE_TBD", 1, 162, 160);
                AttachTrialInterruption(trial, qf1, 1, "DRV_L", 20, true, 100);
                AttachTrialInterruption(trial, qf1, 3, "DRV_N", 20, true, 100);
                AttachTrialInterruption(trial, lContact, 0, "DRV_L", 20, false, 101);
                AttachTrialInterruption(trial, nContact, 0, "DRV_N", 20, false, 101);
                AttachTrialInterruption(trial, lContact, 1, "VFD_L", 20, true, 100);
                AttachTrialInterruption(trial, nContact, 1, "VFD_N", 20, true, 100);
                AttachTrialInterruption(trial, l, 0, "VFD_L", 20, false, 101);
                AttachTrialInterruption(trial, n, 0, "VFD_N", 20, false, 101);
                string[] phases = { "U", "V", "W" };
                Function[] outputs = new Function[3];
                motor.Location = new PointD(200, 60);
                for (int i = 0; i < 3; i++)
                {
                    outputs[i] = EnsureTrialRolePoint(trial, page4, "VFD1", phases[i], 2, 200 + 8 * i, 124);
                    outputs[i].VisibleName = ""; // Inherit VFD1 from the native black-box logical area.
                    if (!box.IsFunctionInside(outputs[i]) || !outputs[i].Name.EndsWith("-VFD1:" + phases[i], StringComparison.Ordinal))
                        return Error("DEVICE_ASSOCIATION_FAILED", "VFD power role did not inherit its black box");
                    terminals[i].Page = page4; terminals[i].Location = new PointD(200 + 8 * i, 95);
                }
                terminals[0].VisibleName = "X3";
                using (var generator = new Generate()) generator.Connections(trial, false);
                if (!HasPinConnection(qf1, 1, lContact, 0) || !HasPinConnection(qf1, 3, nContact, 0) ||
                    !HasPinConnection(lContact, 1, l, 0) || !HasPinConnection(nContact, 1, n, 0) ||
                    HasPinConnection(qf1, 1, nContact, 0) || HasPinConnection(lContact, 1, n, 0))
                    return Error("ROUTE_MISMATCH", "Drive input L/N mapping mismatch");
                for (int i = 0; i < 3; i++)
                {
                    if (!HasPinConnection(outputs[i], 0, terminals[i], 0) || !HasPinConnection(terminals[i], 1, motor, i))
                        return Error("ROUTE_MISMATCH", "Drive motor phase mapping mismatch");
                    for (int j = 0; j < 3; j++)
                        if (j != i && (HasPinConnection(outputs[i], 0, terminals[j], 0) || HasPinConnection(terminals[i], 1, motor, j)))
                            return Error("FORBIDDEN_CONNECTION", "Motor phases cross-connected");
                }
                return Ok(new Dictionary<string, object> { { "placed_native_connections", 10 },
                    { "VFD_power_role_points", 6 }, { "motor_phases_verified", true },
                    { "motor_PE_pin_potential", motor.Pins[3].Potential.ToString() },
                    { "physical_ratings_and_PE_complete", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> RouteTrialAuxNeutral(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page2 = FindTrialPage(trial, "/2"), page8 = FindTrialPage(trial, "/8");
            if (page2 == null || page8 == null) return Error("PAGE_NOT_FOUND", "Aux neutral pages");
            Function qf0 = FindTrialFunction(page2, "QF0", "FA2");
            Function fan = FindTrialFunction(page8, "FAN1", "M2W_VE"), light = FindTrialFunction(page8, "EL1", "H");
            if (qf0 == null || fan == null || light == null) return Error("FUNCTION_NOT_FOUND", "Aux neutral endpoints");
            try
            {
                Terminal fanN = FindTrialTerminal(trial, "X4", "2"), lightN = FindTrialTerminal(trial, "X4", "4");
                trial.LockAllObjects();
                fanN.Page = page8; fanN.Location = new PointD(96, 180);
                lightN.Page = page8; lightN.Location = new PointD(180, 70);
                AttachTrialInterruption(trial, fanN, 0, "AC_N", 20, false, 201);
                AttachTrialInterruption(trial, lightN, 1, "AC_N", 20, false, 202);
                using (var generator = new Generate()) generator.Connections(trial, false);
                if (!HasPinConnection(fan, 1, fanN, 1) || !HasPinConnection(light, 1, lightN, 0) ||
                    !HasPinConnection(qf0, 3, fanN, 0) || !HasPinConnection(qf0, 3, lightN, 1) ||
                    HasPinConnection(qf0, 1, fanN, 0) || HasPinConnection(qf0, 1, lightN, 1))
                    return Error("ROUTE_MISMATCH", "Aux neutral exact pin path mismatch");
                return Ok(new Dictionary<string, object> { { "placed_native_connections", 4 },
                    { "fan_and_light_ac_return_paths_verified", true }, { "device_PE_requirement_TBD", true } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static void UpgradeTrialFuseLayout(Page page, Function fuse)
        {
            if (Math.Abs(fuse.Location.X - 120.0) > 0.001 ||
                (Math.Abs(fuse.Location.Y - 190.0) > 0.001 && Math.Abs(fuse.Location.Y - 210.0) > 0.001))
                throw new InvalidOperationException("FU2 layout differs from known draft revisions");
            var changes = new List<InterruptionPoint>();
            foreach (Placement placement in page.AllPlacements)
            {
                InterruptionPoint point = placement as InterruptionPoint;
                if (point == null) continue;
                bool input = point.VisibleName == "DC24" && !point.Properties.INTERRUPTIONPOINT_SORT_CODE.IsEmpty &&
                    point.Properties.INTERRUPTIONPOINT_SORT_CODE.ToString() == "102";
                bool output = point.VisibleName == "INPUT24" && point.IsStarSource;
                if (!input && !output) continue;
                double oldY = input ? 214.0 : 176.0, newY = oldY + 20.0;
                if (Math.Abs(point.Location.X - 120.0) > 0.001 ||
                    (Math.Abs(point.Location.Y - oldY) > 0.001 && Math.Abs(point.Location.Y - newY) > 0.001) ||
                    point.SymbolVariant.SymbolName != "BPIN" || point.SymbolVariant.VariantNr != (input ? 1 : 3))
                    throw new InvalidOperationException("FU2 interruption differs from known draft revisions");
                changes.Add(point);
            }
            fuse.Location = new PointD(120, 210);
            foreach (InterruptionPoint point in changes)
                point.Location = new PointD(120, point.VisibleName == "DC24" ? 234.0 : 196.0);
        }

        private Dictionary<string, object> RouteTrialDcDistribution(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page3 = FindTrialPage(trial, "/3"), page6 = FindTrialPage(trial, "/6"), page7 = FindTrialPage(trial, "/7");
            if (page3 == null || page6 == null || page7 == null) return Error("PAGE_NOT_FOUND", "DC distribution pages");
            try
            {
                Function[] fuses = new Function[3];
                for (int i = 0; i < 3; i++)
                {
                    fuses[i] = FindTrialFunction(page3, "FU" + (i + 1).ToString(), "FA1");
                    if (fuses[i] == null) return Error("FUNCTION_NOT_FOUND", "DC fuse");
                }
                Function lamp = FindTrialFunction(page3, "HL2", "H");
                if (lamp == null) return Error("FUNCTION_NOT_FOUND", "HL2");
                Terminal common = FindTrialTerminal(trial, "X2", "1"), zeroTerminal = FindTrialTerminal(trial, "X2", "6");
                string[] tags = { "KA1", "KA2", "KA3", "HL3", "HL4", "HL5" };
                string[] symbols = { "K", "K", "K", "H", "H", "H" };
                Function[] loads = new Function[6];
                for (int i = 0; i < loads.Length; i++)
                {
                    loads[i] = FindTrialFunction(page7, tags[i], symbols[i]);
                    if (loads[i] == null) return Error("FUNCTION_NOT_FOUND", tags[i]);
                }
                Function[] buttons = new Function[4];
                for (int i = 0; i < buttons.Length; i++)
                {
                    buttons[i] = FindTrialFunction(page6, "SB" + (i + 1).ToString(), i == 1 ? "SOA" : "SSA");
                    if (buttons[i] == null) return Error("FUNCTION_NOT_FOUND", "DC button");
                }
                trial.LockAllObjects();
                UpgradeTrialFuseLayout(page3, fuses[1]);
                Function plus = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_24V_TBD", 3, 228, 170);
                Function zero = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_0V_TBD", 3, 228, 130);
                Function plcPlus = EnsureTrialRolePoint(trial, page3, "PLC1", "ROLE_LPLUS_TBD", 1, 340, 180);
                Function plcZero = EnsureTrialRolePoint(trial, page3, "PLC1", "ROLE_M_TBD", 1, 340, 150);
                Function plcDoPlus = EnsureTrialRolePoint(trial, page3, "PLC1", "ROLE_DO_LPLUS_TBD", 1, 340, 120);
                common.Page = page6; common.Location = new PointD(280, 210);
                zeroTerminal.Page = page6; zeroTerminal.Location = new PointD(280, 80);
                AttachTrialInterruption(trial, plus, 0, "DC24", 20, true, 100);
                for (int i = 0; i < fuses.Length; i++) AttachTrialInterruption(trial, fuses[i], 0, "DC24", 20, false, 101 + i);
                AttachTrialInterruption(trial, lamp, 0, "DC24", 20, false, 104);
                AttachTrialInterruption(trial, fuses[0], 1, "PLC24", 20, true, 100);
                AttachTrialInterruption(trial, plcPlus, 0, "PLC24", 20, false, 101);
                AttachTrialInterruption(trial, fuses[1], 1, "INPUT24", 10, true, 100);
                AttachTrialInterruption(trial, common, 0, "INPUT24", 20, false, 101);
                AttachTrialInterruption(trial, common, 1, "PB24", 20, true, 100);
                for (int i = 0; i < buttons.Length; i++) AttachTrialInterruption(trial, buttons[i], 0, "PB24", 20, false, 101 + i);
                AttachTrialInterruption(trial, fuses[2], 1, "OUTPUT24", 20, true, 100);
                AttachTrialInterruption(trial, plcDoPlus, 0, "OUTPUT24", 20, false, 101);
                AttachTrialInterruption(trial, zero, 0, "DC0", 20, true, 100);
                AttachTrialInterruption(trial, plcZero, 0, "DC0", 20, false, 101);
                AttachTrialInterruption(trial, lamp, 1, "DC0", 20, false, 102);
                AttachTrialInterruption(trial, zeroTerminal, 0, "DC0", 20, false, 103);
                for (int i = 0; i < loads.Length; i++) AttachTrialInterruption(trial, loads[i], 0, "DC0", 20, false, 201 + i);
                using (var generator = new Generate()) generator.Connections(trial, false);
                for (int i = 0; i < fuses.Length; i++)
                    if (!HasPinConnection(plus, 0, fuses[i], 0)) return Error("ROUTE_MISMATCH", "24V fuse feed");
                if (!HasPinConnection(plus, 0, lamp, 0) || !HasPinConnection(fuses[0], 1, plcPlus, 0) ||
                    !HasPinConnection(fuses[1], 1, common, 0) || !HasPinConnection(fuses[2], 1, plcDoPlus, 0) ||
                    !HasPinConnection(zero, 0, plcZero, 0) || !HasPinConnection(zero, 0, lamp, 1) ||
                    !HasPinConnection(zero, 0, zeroTerminal, 0) || HasConnection(plus, zero))
                    return Error("ROUTE_MISMATCH", "DC source/return or PLC supply mismatch");
                for (int i = 0; i < buttons.Length; i++)
                    if (!HasPinConnection(common, 1, buttons[i], 0)) return Error("ROUTE_MISMATCH", "Button supply");
                for (int i = 0; i < loads.Length; i++)
                    if (!HasPinConnection(zero, 0, loads[i], 0)) return Error("ROUTE_MISMATCH", "DC load return");
                return Ok(new Dictionary<string, object> { { "placed_native_connections", 20 },
                    { "PLC_supply_role_points", 3 }, { "button_and_load_returns_verified", true },
                    { "whole_project_audit_required", true },
                    { "output_topology", "draft_24V_sourcing_assumption" }, { "physical_plc_terminals_verified", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static void MigrateTrialPsInputLabel(Page page, string name, double oldY)
        {
            InterruptionPoint found = null;
            foreach (Placement placement in page.AllPlacements)
            {
                InterruptionPoint point = placement as InterruptionPoint;
                if (point == null || point.VisibleName != name) continue;
                if (found != null) throw new InvalidOperationException("Ambiguous PS1 input interruption");
                found = point;
            }
            if (found == null) return;
            if (found.SymbolVariant.SymbolName != "BPIN" || found.SymbolVariant.VariantNr != 2 ||
                Math.Abs(found.Location.Y - oldY) > 0.001 ||
                (Math.Abs(found.Location.X - 120.0) > 0.001 && Math.Abs(found.Location.X - 100.0) > 0.001))
                throw new InvalidOperationException("PS1 input label differs from known layout revisions");
            found.Location = new PointD(100.0, oldY);
        }

        private Dictionary<string, object> PlaceTrialPs1Interfaces(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page2 = FindTrialPage(trial, "/2"), page3 = FindTrialPage(trial, "/3");
            if (page2 == null || page3 == null) return Error("PAGE_NOT_FOUND", "PS1 interface pages");
            Function qf2 = FindTrialFunction(page2, "QF2", "FA2");
            BoxedDevice box = null;
            foreach (BoxedDevice candidate in page3.BoxedDevices) if (candidate.VisibleName == "PS1") box = candidate;
            if (qf2 == null || box == null) return Error("FUNCTION_NOT_FOUND", "QF2 or PS1 box");
            try
            {
                trial.LockAllObjects();
                box.SetLogicalArea(new PointD(140.0, 110.0), new PointD(230.0, 190.0));
                Function l = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_L_TBD", 1, 142, 170);
                Function n = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_N_TBD", 1, 142, 150);
                Function pe = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_PE_TBD", 1, 142, 130);
                Function plus = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_24V_TBD", 3, 228, 170);
                Function zero = EnsureTrialRolePoint(trial, page3, "PS1", "ROLE_0V_TBD", 3, 228, 130);
                MigrateTrialPsInputLabel(page3, "MFR_PS_L", 170.0);
                MigrateTrialPsInputLabel(page3, "MFR_PS_N", 150.0);
                AttachTrialInterruption(trial, qf2, 1, "MFR_PS_L", 22, true, 100);
                AttachTrialInterruption(trial, qf2, 3, "MFR_PS_N", 22, true, 100);
                AttachTrialInterruption(trial, l, 0, "MFR_PS_L", 40, false, 101);
                AttachTrialInterruption(trial, n, 0, "MFR_PS_N", 40, false, 101);
                using (var generator = new Generate()) generator.Connections(trial);
                if (!HasPinConnection(qf2, 1, l, 0) || !HasPinConnection(qf2, 3, n, 0) ||
                    HasPinConnection(qf2, 1, n, 0) || HasPinConnection(qf2, 3, l, 0))
                    return Error("ROUTE_MISMATCH", "PS1 AC interfaces failed exact native readback");
                return Ok(new Dictionary<string, object> { { "logical_role_points", 5 },
                    { "placed_native_connections", 2 }, { "L_N_separation_verified", true },
                    { "physical_terminal_labels_verified", false }, { "PE_and_DC_output_complete", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> RouteTrialAcDistribution(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page = FindTrialPage(trial, "/2");
            if (page == null) return Error("PAGE_NOT_FOUND", "/2");
            Function source = FindTrialFunction(page, "QF0", "FA2");
            string[] tags = { "QF1", "QF2", "QF3", "QF4", "HL1" };
            string[] symbols = { "FA2", "FA2", "FA1", "FA1", "H" };
            Function[] targets = new Function[5];
            for (int i = 0; i < targets.Length; i++)
            {
                targets[i] = FindTrialFunction(page, tags[i], symbols[i]);
                if (targets[i] == null) return Error("FUNCTION_NOT_FOUND", tags[i]);
            }
            if (source == null) return Error("FUNCTION_NOT_FOUND", "QF0");
            try
            {
                trial.LockAllObjects();
                AttachTrialInterruption(trial, source, 1, "AC_L", 20.0, true, 100);
                AttachTrialInterruption(trial, source, 3, "AC_N", 20.0, true, 100);
                for (int i = 0; i < targets.Length; i++)
                {
                    AttachTrialInterruption(trial, targets[i], 0, "AC_L", 20.0, false, 101 + i);
                    if (i < 2) AttachTrialInterruption(trial, targets[i], 2, "AC_N", 20.0, false, 101 + i);
                    if (i == 4) AttachTrialInterruption(trial, targets[i], 1, "AC_N", 20.0, false, 105);
                }
                using (var generator = new Generate()) generator.Connections(trial, false);
                for (int i = 0; i < targets.Length; i++)
                {
                    if (!HasPinConnection(source, 1, targets[i], 0) || HasPinConnection(source, 3, targets[i], 0))
                        return Error("ROUTE_MISMATCH", "AC L star route mismatch " + tags[i]);
                    int neutral = i < 2 ? 2 : (i == 4 ? 1 : -1);
                    if (neutral >= 0 && (!HasPinConnection(source, 3, targets[i], neutral) ||
                        HasPinConnection(source, 1, targets[i], neutral)))
                        return Error("ROUTE_MISMATCH", "AC N star route mismatch " + tags[i]);
                }
                return Ok(new Dictionary<string, object> { { "placed_native_distribution_edges", 8 },
                    { "L_targets", 5 }, { "N_targets", 3 }, { "L_N_separation_verified", true },
                    { "logical_bus_nodes_collapsed_to_native_star", true } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> RouteTrialAuxFeeds(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page2 = FindTrialPage(trial, "/2"), page8 = FindTrialPage(trial, "/8"), page9 = FindTrialPage(trial, "/9");
            if (page2 == null || page8 == null || page9 == null) return Error("PAGE_NOT_FOUND", "Auxiliary feed pages");
            string[] qfTags = { "QF3", "QF4" }, swTags = { "SQ1", "TS1" }, names = { "MFR_LIGHT_L", "MFR_FAN_L" };
            string[] numbers = { "3", "1" };
            Function[] breakers = new Function[2], switches = new Function[2];
            Terminal[] terminals = new Terminal[2];
            for (int i = 0; i < 2; i++)
            {
                breakers[i] = FindTrialFunction(page2, qfTags[i], "FA1");
                switches[i] = FindTrialFunction(page8, swTags[i], "SSM");
                foreach (TerminalStrip strip in page9.TerminalStrips)
                    if (strip.VisibleName == "X4")
                        foreach (Terminal t in strip.Terminals)
                            if (!t.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty &&
                                t.Properties.FUNC_PINORTERMINALNUMBER.ToString() == numbers[i])
                            {
                                if (terminals[i] != null) return Error("TERMINAL_AMBIGUOUS", "X4:" + numbers[i]);
                                terminals[i] = t;
                            }
                if (breakers[i] == null || switches[i] == null || terminals[i] == null)
                    return Error("ENDPOINT_NOT_FOUND", qfTags[i] + "/" + swTags[i] + "/X4");
            }
            try
            {
                trial.LockAllObjects();
                var points = new List<InterruptionPoint>();
                for (int i = 0; i < 2; i++)
                {
                    double targetX = i == 0 ? 180.0 : 80.0;
                    terminals[i].Page = page8;
                    terminals[i].Location = new PointD(targetX, 210.0);
                    points.Add(EnsureTrialInterruption(trial, page2, names[i], 3, i == 0 ? 210.0 : 250.0, 90.0, true));
                    points.Add(EnsureTrialInterruption(trial, page8, names[i], 1, targetX, 240.0, false));
                }
                using (var generator = new Generate()) generator.Connections(trial);
                for (int i = 0; i < 2; i++)
                {
                    if (!HasPinConnection(breakers[i], 1, terminals[i], 0) ||
                        !HasPinConnection(terminals[i], 1, switches[i], 0) ||
                        HasConnection(breakers[i], terminals[1 - i]) ||
                        HasConnection(terminals[i], switches[1 - i]) || terminals[i].Connections.Length != 2)
                        return Error("ROUTE_MISMATCH", "Auxiliary cross-page feed failed exact pin readback");
                }
                foreach (InterruptionPoint point in points)
                    if (point.GraphicalConnections.Length != 1)
                        return Error("INTERRUPTION_GRAPHICS_MISMATCH", point.VisibleName);
                return Ok(new Dictionary<string, object> { { "placed_native_connections", 4 },
                    { "interruption_points", 4 }, { "required_and_forbidden_pairs_verified", true },
                    { "neutral_and_upstream_supply_complete", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> RouteTrialAcInput(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page2 = FindTrialPage(trial, "/2");
            Page page9 = FindTrialPage(trial, "/9");
            if (page2 == null || page9 == null) return Error("PAGE_NOT_FOUND", "/2 or /9");
            Function qs = FindTrialFunction(page2, "QS1", "Q2");
            Function qf = FindTrialFunction(page2, "QF0", "FA2");
            if (qs == null || qf == null) return Error("FUNCTION_NOT_FOUND", "QS1/QF0");
            Terminal[] terminals = new Terminal[2];
            foreach (TerminalStrip strip in page9.TerminalStrips)
                if (strip.VisibleName == "X1")
                    foreach (Terminal t in strip.Terminals)
                        for (int i = 0; i < 2; i++)
                            if (!t.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty &&
                                t.Properties.FUNC_PINORTERMINALNUMBER.ToString() == (i + 1).ToString())
                            {
                                if (terminals[i] != null) return Error("TERMINAL_AMBIGUOUS", "X1");
                                terminals[i] = t;
                            }
            if (terminals[0] == null || terminals[1] == null || qs.GraphicalConnectionPoints.Length != 4 ||
                qf.GraphicalConnectionPoints.Length != 4) return Error("PIN_MAP_UNVERIFIED", "AC input endpoint missing or unexpected pin count");
            try
            {
                trial.LockAllObjects();
                for (int i = 0; i < 2; i++)
                {
                    terminals[i].Page = page2;
                    terminals[i].Location = new PointD(50.0 + 16.0 * i, 240.0);
                }
                qs.Location = new PointD(50.0, 200.0);
                qf.Location = new PointD(50.0, 150.0);
                using (var generator = new Generate()) generator.Connections(trial);
                bool l1 = HasPinConnection(terminals[0], 1, qs, 0);
                bool n1 = HasPinConnection(terminals[1], 1, qs, 2);
                bool l2 = HasPinConnection(qs, 1, qf, 0);
                bool n2 = HasPinConnection(qs, 3, qf, 2);
                if (!l1 || !n1 || !l2 || !n2 || qs.Connections.Length != 4 ||
                    terminals[0].Connections.Length != 1 || terminals[1].Connections.Length != 1)
                    return Error("ROUTE_MISMATCH", "AC input L/N exact pin readback mismatch");
                return Ok(new Dictionary<string, object> { { "x1_to_qs1_L", l1 }, { "x1_to_qs1_N", n1 },
                    { "qs1_to_qf0_L", l2 }, { "qs1_to_qf0_N", n2 }, { "placed_native_connections", 4 },
                    { "downstream_distribution_complete", false }, { "device_ratings_verified", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static bool HasPinConnection(Function a, int ai, Function b, int bi)
        {
            int matches = 0;
            bool placed = false;
            foreach (Connection edge in a.Connections)
                if ((edge.StartSymbolReference == a && edge.StartIndex == ai && edge.EndSymbolReference == b && edge.EndIndex == bi) ||
                    (edge.StartSymbolReference == b && edge.StartIndex == bi && edge.EndSymbolReference == a && edge.EndIndex == ai))
                { matches++; placed = edge.IsPlaced; }
            return matches == 1 && placed;
        }

        private Dictionary<string, object> RouteTrialPlcInputs(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page6 = FindTrialPage(trial, "/6");
            Page page9 = FindTrialPage(trial, "/9");
            if (page6 == null || page9 == null) return Error("PAGE_NOT_FOUND", "/6 or /9");
            TerminalStrip strip = null;
            foreach (TerminalStrip candidate in page9.TerminalStrips)
                if (candidate.VisibleName == "X2")
                {
                    if (strip != null) return Error("STRIP_AMBIGUOUS", "X2");
                    strip = candidate;
                }
            if (strip == null) return Error("STRIP_NOT_FOUND", "X2");
            string[] buttonTags = { "SB1", "SB2", "SB3", "SB4" };
            string[] symbols = { "SSA", "SOA", "SSA", "SSA" };
            Function[] buttons = new Function[4];
            Terminal[] terminals = new Terminal[4];
            Terminal[] inputs = new Terminal[4];
            for (int i = 0; i < 4; i++)
            {
                buttons[i] = FindTrialFunction(page6, buttonTags[i], symbols[i]);
                if (buttons[i] == null) return Error("FUNCTION_NOT_FOUND", buttonTags[i]);
                foreach (Terminal candidate in strip.Terminals)
                    if (!candidate.Properties.FUNC_PINORTERMINALNUMBER.IsEmpty &&
                        candidate.Properties.FUNC_PINORTERMINALNUMBER.ToString() == (i + 2).ToString())
                    {
                        if (terminals[i] != null) return Error("TERMINAL_AMBIGUOUS", "X2:" + (i + 2).ToString());
                        terminals[i] = candidate;
                    }
                foreach (Function f in page6.Functions)
                {
                    Terminal candidate = f as Terminal;
                    if (candidate == null || candidate.SymbolVariant == null ||
                        candidate.SymbolVariant.SymbolName != "PLCCP" || candidate.Properties.FUNC_PLCADDRESS.IsEmpty) continue;
                    if (candidate.Properties.FUNC_PLCADDRESS.ToString() != "I0." + i.ToString()) continue;
                    if (inputs[i] != null) return Error("PLC_ADDRESS_AMBIGUOUS", "I0." + i.ToString());
                    inputs[i] = candidate;
                }
                if (terminals[i] == null || inputs[i] == null) return Error("ENDPOINT_NOT_FOUND", "X2/PLC input");
                if (buttons[i].GraphicalConnectionPoints.Length != 2 ||
                    terminals[i].GraphicalConnectionPoints.Length != 2 || inputs[i].GraphicalConnectionPoints.Length != 1)
                    return Error("PIN_MAP_UNVERIFIED", "Unexpected input-chain pin count");
            }
            try
            {
                trial.LockAllObjects();
                for (int i = 0; i < 4; i++)
                {
                    double x = 50.0 + i * 50.0;
                    buttons[i].Location = new PointD(x, 180.0);
                    terminals[i].Page = page6;
                    terminals[i].Location = new PointD(x, 140.0);
                    inputs[i].Location = new PointD(x, 100.0);
                }
                using (var generator = new Generate()) generator.Connections(trial);
                var routes = new List<Dictionary<string, object>>();
                bool allButtonsSupplied = true;
                for (int i = 0; i < 4; i++)
                {
                    Terminal commonSupply = FindTrialTerminal(trial, "X2", "1");
                    bool supplied = HasPinConnection(commonSupply, 1, buttons[i], 0);
                    allButtonsSupplied = allButtonsSupplied && supplied;
                    if (!HasPinConnection(buttons[i], 1, terminals[i], 0) || !HasPinConnection(terminals[i], 1, inputs[i], 0) ||
                        HasConnection(buttons[i], inputs[i]) || buttons[i].Connections.Length != (supplied ? 2 : 1) ||
                        terminals[i].Connections.Length != 2 || inputs[i].Connections.Length != 1 ||
                        buttons[i].GraphicalConnections.Length != (supplied ? 2 : 1) || terminals[i].GraphicalConnections.Length != 2 ||
                        inputs[i].GraphicalConnections.Length != 1)
                        return Error("ROUTE_MISMATCH", buttonTags[i] + " terminal/PLC chain readback mismatch");
                    for (int j = 0; j < 4; j++)
                        if (j != i && (HasConnection(buttons[i], terminals[j]) || HasConnection(terminals[i], inputs[j])))
                            return Error("FORBIDDEN_CONNECTION", "Input channels cross-connected");
                    routes.Add(new Dictionary<string, object> { { "button", buttonTags[i] },
                        { "terminal", "X2:" + (i + 2).ToString() }, { "address", "I0." + i.ToString() },
                        { "placed_native_connections", 2 } });
                }
                return Ok(new Dictionary<string, object> { { "routes", routes },
                    { "button_supply_complete", allButtonsSupplied }, { "physical_plc_pins_verified", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> RouteTrialAuxServices(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page = FindTrialPage(trial, "/8");
            if (page == null) return Error("PAGE_NOT_FOUND", "/8");
            Function thermostat = FindTrialFunction(page, "TS1", "SSM");
            Function fan = FindTrialFunction(page, "FAN1", "M2W_VE");
            Function door = FindTrialFunction(page, "SQ1", "SSM");
            Function light = FindTrialFunction(page, "EL1", "H");
            if (thermostat == null || fan == null || door == null || light == null)
                return Error("FUNCTION_NOT_FOUND", "TS1/FAN1/SQ1/EL1 not uniquely placed");
            if (thermostat.GraphicalConnectionPoints.Length != 2 ||
                fan.GraphicalConnectionPoints.Length != 3 ||
                door.GraphicalConnectionPoints.Length != 2 ||
                light.GraphicalConnectionPoints.Length != 2)
                return Error("PIN_MAP_UNVERIFIED", "Unexpected trial auxiliary symbol pin count");
            try
            {
                trial.LockAllObjects();
                thermostat.Location = new PointD(80.0, 160.0);
                fan.Location = new PointD(80.0, 110.0);
                door.Location = new PointD(180.0, 160.0);
                light.Location = new PointD(180.0, 110.0);
                using (var generator = new Generate()) generator.Connections(trial);
                bool fanRoute = HasPinConnection(thermostat, 1, fan, 0);
                bool lightRoute = HasPinConnection(door, 1, light, 0);
                bool forbidden = HasConnection(thermostat, light) ||
                                 HasConnection(door, fan) || HasConnection(fan, light);
                if (!fanRoute || !lightRoute || forbidden ||
                    thermostat.GraphicalConnections.Length < 1 ||
                    door.GraphicalConnections.Length < 1)
                    return Error("ROUTE_MISMATCH", "Required auxiliary routes missing or forbidden route detected");
                return Ok(new Dictionary<string, object> {
                    { "ts1_to_fan1_native", fanRoute }, { "sq1_to_el1_native", lightRoute },
                    { "forbidden_cross_connection", forbidden },
                    { "ts1_graphical_count", thermostat.GraphicalConnections.Length },
                    { "sq1_graphical_count", door.GraphicalConnections.Length },
                    { "physical_pin_numbers_verified", false }
                });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }
        private Dictionary<string, object> TrialAssetCatalog(ProjectManager pm, Project[] projects, Dictionary<string, object> payload)
        {
            string category = payload != null && payload.ContainsKey("category") ? Convert.ToString(payload["category"]) : "";
            string[] needles;
            switch (category)
            {
                case "power": needles = new[] { "power supply", "transformer", "rectifier" }; break;
                case "drive": needles = new[] { "frequency converter", "inverter", "variable frequency", "motor drive" }; break;
                case "converter": needles = new[] { "converter", "inverter", "rectifier" }; break;
                case "box": needles = new[] { "black box", "device box", "box", "general device" }; break;
                case "plc": needles = new[] { "plc", "programmable logic", "digital input", "digital output" }; break;
                case "terminal": needles = new[] { "terminal", "connector" }; break;
                case "lamp": needles = new[] { "lamp", "indicator light", "illumination" }; break;
                case "fan": needles = new[] { "fan", "ventilator" }; break;
                case "breaker": needles = new[] { "circuit breaker", "fuse", "load-break", "isolator" }; break;
                case "safety": needles = new[] { "safety relay", "emergency stop" }; break;
                default: return Error("INVALID_CATEGORY", "Category is not in the fixed asset search allowlist");
            }
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = false;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            var found = new List<Dictionary<string, object>>();
            foreach (SymbolLibrary lib in trial.SymbolLibraries)
            {
                foreach (Symbol s in lib.Symbols)
                {
                    string description = s.Properties.SYMB_DESC.ToString();
                    string english = "";
                    foreach (string part in description.Split(';'))
                        if (part.StartsWith("en_US@", StringComparison.Ordinal)) english = part.Substring(6);
                    bool matched = false;
                    foreach (string needle in needles)
                        if (english.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0) matched = true;
                    if (!matched) continue;
                    found.Add(new Dictionary<string, object> { { "library", lib.Name },
                        { "symbol", s.Properties.SYMB_NAME.ToString() }, { "english_description", english } });
                    if (found.Count >= 60) break;
                }
                if (found.Count >= 60) break;
            }
            return Ok(new Dictionary<string, object> { { "category", category }, { "symbols", found } });
        }

        private Dictionary<string, object> ReconcileTrialInterlocks(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page7 = null;
            foreach (Page p in trial.Pages) if (p.IdentifyingName == "/7") page7 = p;
            if (page7 == null) return Error("PAGE_NOT_FOUND", "Trial page /7 missing");
            Function ka1Coil = FindTrialFunction(page7, "KA1", "K");
            Function ka2Coil = FindTrialFunction(page7, "KA2", "K");
            Function ka1NC = FindTrialFunction(page7, "KA1", "O");
            Function ka2NC = FindTrialFunction(page7, "KA2", "O");
            if (ka1Coil == null || ka2Coil == null || ka1NC == null || ka2NC == null)
                return Error("FUNCTION_NOT_FOUND", "Interlock functions missing");
            try
            {
                trial.LockAllObjects();
                int removed = 0;
                foreach (Connection c in ka2NC.Connections)
                    if (!c.IsPlaced && c.IsRemovable && IsPair(c, ka2NC, ka1Coil)) { c.Remove(); removed++; }
                foreach (Connection c in ka1NC.Connections)
                    if (!c.IsPlaced && c.IsRemovable && IsPair(c, ka1NC, ka2Coil)) { c.Remove(); removed++; }
                if (!HasPinConnection(ka2NC, 0, ka1Coil, 1) || !HasPinConnection(ka1NC, 0, ka2Coil, 1))
                    return Error("PARTIAL_NATIVE_WRITE", "Interlock still has duplicate or missing native connections");
                if (ka2NC.GraphicalConnections.Length < 1 || ka1NC.GraphicalConnections.Length < 1)
                    return Error("PARTIAL_NATIVE_WRITE", "Interlock placed connection readback failed");
                return Ok(new Dictionary<string, object> { { "removed_unplaced_duplicates", removed },
                    { "placed_interlock_connections", 2 }, { "graphical_lines", 2 } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static bool IsPair(Connection edge, Function left, Function right)
        {
            return (edge.StartSymbolReference == left && edge.EndSymbolReference == right) ||
                   (edge.StartSymbolReference == right && edge.EndSymbolReference == left);
        }

        private Dictionary<string, object> RouteTrialInterlocks(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page7 = null;
            foreach (Page p in trial.Pages) if (p.IdentifyingName == "/7") page7 = p;
            if (page7 == null) return Error("PAGE_NOT_FOUND", "Trial page /7 missing");
            Function ka1Coil = FindTrialFunction(page7, "KA1", "K");
            Function ka2Coil = FindTrialFunction(page7, "KA2", "K");
            Function ka1NC = FindTrialFunction(page7, "KA1", "O");
            Function ka2NC = FindTrialFunction(page7, "KA2", "O");
            if (ka1Coil == null || ka2Coil == null || ka1NC == null || ka2NC == null)
                return Error("FUNCTION_NOT_FOUND", "Interlock functions missing");
            try
            {
                trial.LockAllObjects();
                // Both pin pairs face each other vertically; the remaining relay symbols stay separate.
                ka2NC.Location = new PointD(60.0, 80.0);
                ka1NC.Location = new PointD(110.0, 80.0);
                using (var generator = new Generate()) generator.Connections(trial);
                if (!HasPinConnection(ka2NC, 0, ka1Coil, 1) || !HasPinConnection(ka1NC, 0, ka2Coil, 1))
                    return Error("ROUTE_MISMATCH", "Interlock pin pairs are missing, duplicate or unplaced");
                return Ok(new Dictionary<string, object> { { "ka2_nc_graphical", ka2NC.GraphicalConnections.Length },
                    { "ka1_coil_graphical", ka1Coil.GraphicalConnections.Length },
                    { "ka1_nc_graphical", ka1NC.GraphicalConnections.Length },
                    { "ka2_coil_graphical", ka2Coil.GraphicalConnections.Length },
                    { "ka2_nc_to_ka1_coil_native", HasConnection(ka2NC, ka1Coil) },
                    { "ka1_nc_to_ka2_coil_native", HasConnection(ka1NC, ka2Coil) } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> ExportTrialPdf(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            string output = RuntimePath(@"artifacts\trial_native_pages.pdf");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = false;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            ArrayList pages = new ArrayList();var ordered=new SortedDictionary<int,Page>();
            foreach(Page page in trial.Pages){int n;if(!Int32.TryParse(page.IdentifyingName.TrimStart('/'),out n)||ordered.ContainsKey(n))return Error("EXPORT_PAGE_IDENTITY_UNSUPPORTED","Cannot silently omit or reorder unknown page identities");ordered[n]=page;}
            for(int n=1;n<=9;n++)if(!ordered.ContainsKey(n))return Error("PAGES_MISSING","Required trial page missing");
            foreach(var pair in ordered)pages.Add(pair.Value);
            try
            {
                using (var exporter = new Export())
                    exporter.PdfPages(pages, "EPLAN_default_value", output,
                        Export.DegreeOfColor.BlackAndWhite, true, "", true);
                if (!File.Exists(output) || new FileInfo(output).Length == 0)
                    return Error("EXPORT_FAILED", "PDF not created or empty");
                return Ok(new Dictionary<string, object> { { "pdf", output },
                    { "bytes", new FileInfo(output).Length }, { "pages_requested", pages.Count } });
            }
            catch (Exception ex) { return Error("EXPORT_FAILED", ex.Message); }
        }

        private Dictionary<string, object> ConnectTrialInterlocks(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page page7 = null;
            foreach (Page page in trial.Pages) if (page.IdentifyingName == "/7") page7 = page;
            if (page7 == null) return Error("PAGE_NOT_FOUND", "Trial page /7 does not exist");
            Function ka1Coil = FindTrialFunction(page7, "KA1", "K");
            Function ka2Coil = FindTrialFunction(page7, "KA2", "K");
            Function ka1NC = FindTrialFunction(page7, "KA1", "O");
            Function ka2NC = FindTrialFunction(page7, "KA2", "O");
            if (ka1Coil == null || ka2Coil == null || ka1NC == null || ka2NC == null)
                return Error("FUNCTION_NOT_FOUND", "Coils or NC contacts are missing");
            if (ka1Coil.Pins.Length != 2 || ka2Coil.Pins.Length != 2 ||
                ka1NC.Pins.Length != 2 || ka2NC.Pins.Length != 2)
                return Error("PIN_MAP_UNVERIFIED", "Unexpected pin count for trial symbols");
            try
            {
                trial.LockAllObjects();
                bool first = HasConnection(ka2NC, ka1Coil);
                bool second = HasConnection(ka1NC, ka2Coil);
                if (!first) new Connection(trial, ka2NC.Pins[1], ka1Coil.Pins[0]);
                if (!second) new Connection(trial, ka1NC.Pins[1], ka2Coil.Pins[0]);
                bool firstAfter = HasConnection(ka2NC, ka1Coil);
                bool secondAfter = HasConnection(ka1NC, ka2Coil);
                if (!firstAfter || !secondAfter)
                    return Error("PARTIAL_NATIVE_WRITE", "Unplaced connection readback did not match interlock pairs");
                return Ok(new Dictionary<string, object> { { "ka2_nc_to_ka1_coil", firstAfter },
                    { "ka1_nc_to_ka2_coil", secondAfter }, { "native_unplaced_connections", true },
                    { "visible_wire_routes_verified", false }, { "pin_direction_mapping", "TRIAL_PROVISIONAL" } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static Function FindTrialFunction(Page page, string tag, string symbolName)
        {
            Function found = null;
            foreach (Function f in page.Functions)
                if (f.VisibleName == tag && f.SymbolVariant != null && f.SymbolVariant.SymbolName == symbolName)
                {
                    if (found != null) return null;
                    found = f;
                }
            return found;
        }

        private static bool HasConnection(Function source, Function target)
        {
            foreach (Connection c in source.Connections)
                if (c.StartSymbolReference == target || c.EndSymbolReference == target) return true;
            return false;
        }

        private Dictionary<string, object> SetTrialPageDescriptions(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            string[] titles = { "项目说明与目录", "AC220V 输入与分配", "DC24V 控制电源",
                "电机与变频器动力", "急停与安全链", "PLC 输入", "PLC 输出与方向互锁",
                "风扇与柜内照明", "端子与外部接线" };
            var readback = new List<Dictionary<string, object>>();
            try
            {
                trial.LockAllObjects();
                for (int i = 0; i < titles.Length; i++)
                {
                    string pageName = "/" + (i + 1).ToString();
                    Page page = null;
                    foreach (Page candidate in trial.Pages)
                        if (candidate.IdentifyingName == pageName) page = candidate;
                    if (page == null) return Error("PARTIAL_NATIVE_WRITE", "Missing page " + pageName);
                    MultiLangString value = new MultiLangString();
                    value.AddString(ISOCode.Language.L_zh_CN, titles[i]);
                    page.Properties.PAGE_NOMINATIOMN = value;
                    string actual = page.Properties.PAGE_NOMINATIOMN.ToString(ISOCode.Language.L_zh_CN);
                    if (actual != titles[i]) return Error("PARTIAL_NATIVE_WRITE", "Page description readback mismatch " + pageName);
                    readback.Add(new Dictionary<string, object> { { "page", pageName }, { "description", actual } });
                }
                return Ok(new Dictionary<string, object> { { "pages", readback }, { "native_readback", true } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> PlaceTrialControlSymbols(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            var specs = new[] {
                new TrialSpec("/5", "SB0", "SONOT1", 60, 80, 2),
                new TrialSpec("/6", "SB1", "SSA", 50, 80, 1),
                new TrialSpec("/6", "SB2", "SOA", 90, 80, 1),
                new TrialSpec("/6", "SB3", "SSA", 130, 80, 1),
                new TrialSpec("/6", "SB4", "SSA", 170, 80, 1),
                new TrialSpec("/7", "KA1", "S", 50, 60, 1),
                new TrialSpec("/7", "KA1", "O", 50, 80, 1),
                new TrialSpec("/7", "KA2", "S", 100, 60, 1),
                new TrialSpec("/7", "KA2", "O", 100, 80, 1),
                new TrialSpec("/7", "KA3", "S", 150, 60, 1)
            };
            var summary = new List<Dictionary<string, object>>();
            try
            {
                trial.LockAllObjects();
                SymbolLibrary lib = new SymbolLibrary(trial, "GB_symbol");
                foreach (TrialSpec spec in specs)
                {
                    Page page = null;
                    foreach (Page candidate in trial.Pages)
                        if (candidate.IdentifyingName == spec.PageName) page = candidate;
                    if (page == null) return Error("PARTIAL_NATIVE_WRITE", "Trial page missing: " + spec.PageName);
                    int current = CountMatching(page, spec.Tag, spec.SymbolName);
                    while (current < spec.Count)
                    {
                        Symbol symbol = new Symbol(lib, spec.SymbolName);
                        SymbolVariant variant = new SymbolVariant();
                        variant.Initialize(symbol, 0);
                        Function function = new Function();
                        function.Create(page, variant);
                        function.Name = spec.Tag;
                        function.VisibleName = spec.Tag;
                        function.Location = new PointD(spec.X + 40.0 * current, spec.Y);
                        current = CountMatching(page, spec.Tag, spec.SymbolName);
                    }
                    if (current != spec.Count)
                        return Error("PARTIAL_NATIVE_WRITE", "Unexpected count for " + spec.Tag + "/" + spec.SymbolName);
                    summary.Add(new Dictionary<string, object> { { "page", spec.PageName },
                        { "tag", spec.Tag }, { "symbol", spec.SymbolName }, { "count", current } });
                }
                return Ok(new Dictionary<string, object> { { "functions", summary },
                    { "native_function_readback", true }, { "electrical_connections_verified", false } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private static int CountMatching(Page page, string tag, string symbolName)
        {
            int count = 0;
            foreach (Function f in page.Functions)
                if (f.VisibleName == tag && f.SymbolVariant != null && f.SymbolVariant.SymbolName == symbolName) count++;
            return count;
        }

        private sealed class TrialSpec
        {
            public readonly string PageName, Tag, SymbolName;
            public readonly double X, Y;
            public readonly int Count;
            public TrialSpec(string pageName, string tag, string symbolName, double x, double y, int count)
            { PageName = pageName; Tag = tag; SymbolName = symbolName; X = x; Y = y; Count = count; }
        }

        private Dictionary<string, object> PlaceTrialRelayCoils(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page target = null;
            foreach (Page page in trial.Pages)
                if (page.IdentifyingName == "/7") target = page;
            if (target == null) return Error("PAGE_NOT_FOUND", "Trial page /7 does not exist");
            string[] tags = { "KA1", "KA2", "KA3" };
            double[] x = { 60.0, 110.0, 160.0 };
            var status = new List<Dictionary<string, object>>();
            try
            {
                trial.LockAllObjects();
                SymbolLibrary library = new SymbolLibrary(trial, "GB_symbol");
                Symbol symbol = new Symbol(library, "K");
                SymbolVariant variant = new SymbolVariant();
                variant.Initialize(symbol, 0);
                for (int i = 0; i < tags.Length; i++)
                {
                    bool exists = false;
                    foreach (Function f in target.Functions)
                        if (f.VisibleName == tags[i] && f.SymbolVariant != null && f.SymbolVariant.SymbolName == "K") exists = true;
                    if (!exists)
                    {
                        Function coil = new Function();
                        coil.Create(target, variant);
                        coil.Name = tags[i];
                        coil.VisibleName = tags[i];
                        coil.Location = new PointD(x[i], 120.0);
                    }
                    int matches = 0;
                    int points = 0;
                    foreach (Function f in target.Functions)
                        if (f.VisibleName == tags[i]) { matches++; points = f.GraphicalConnectionPoints.Length; }
                    status.Add(new Dictionary<string, object> { { "tag", tags[i] }, { "matches", matches },
                        { "connection_points", points }, { "symbol", "GB_symbol/K" } });
                    if (matches != 1) return Error("PARTIAL_NATIVE_WRITE", "Relay coil readback count was not one");
                }
                return Ok(new Dictionary<string, object> { { "page", "/7" }, { "coils", status },
                    { "native_function_readback", true } });
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> TrialConnectionCatalog(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = false;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            var rows = new List<Dictionary<string, object>>();
            foreach (string libraryName in new[] { "SPECIAL", "GB_symbol" })
            {
                SymbolLibrary library = new SymbolLibrary(trial, libraryName);
                foreach (Symbol symbol in library.Symbols)
                {
                    string description = symbol.Properties.SYMB_DESC.ToString();
                    string english = "";
                    foreach (string part in description.Split(';'))
                        if (part.StartsWith("en_US@", StringComparison.Ordinal)) english = part.Substring(6);
                    if (english.IndexOf("interruption", StringComparison.OrdinalIgnoreCase) < 0 &&
                        english.IndexOf("device connection", StringComparison.OrdinalIgnoreCase) < 0 &&
                        english.IndexOf("potential connection", StringComparison.OrdinalIgnoreCase) < 0) continue;
                    var variants = new List<Dictionary<string, object>>();
                    foreach (SymbolVariant variant in symbol.Variants)
                    {
                        var points = new List<Dictionary<string, object>>();
                        foreach (PinBase pin in variant.ConnectionPoints)
                            points.Add(new Dictionary<string, object> { { "index", pin.Index },
                                { "x", pin.Location.X }, { "y", pin.Location.Y }, { "direction", pin.Direction.ToString() } });
                        variants.Add(new Dictionary<string, object> { { "variant", variant.VariantNr }, { "points", points } });
                    }
                    rows.Add(new Dictionary<string, object> { { "library", libraryName },
                        { "symbol", symbol.Name }, { "description", english }, { "variants", variants } });
                    if (rows.Count >= 60) break;
                }
                if (rows.Count >= 60) break;
            }
            return Ok(new Dictionary<string, object> { { "symbols", rows } });
        }

        private Dictionary<string, object> TrialSymbolCatalog(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                pm.LockProjectByDefault = false;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            SymbolLibrary library = new SymbolLibrary(trial, "GB_symbol");
            var selected = new List<Dictionary<string, object>>();
            foreach (Symbol s in library.Symbols)
            {
                string name = s.Properties.SYMB_NAME.ToString();
                string description = s.Properties.SYMB_DESC.ToString();
                string english = "";
                foreach (string part in description.Split(';'))
                    if (part.StartsWith("en_US@", StringComparison.Ordinal)) english = part.Substring(6);
                bool isContact = english.IndexOf("contact", StringComparison.OrdinalIgnoreCase) >= 0;
                if (!isContact && name != "K" && name != "M3") continue;
                selected.Add(new Dictionary<string, object> { { "name", name },
                    { "english_description", english } });
                if (selected.Count >= 120) break;
            }
            return Ok(new Dictionary<string, object> { { "library", "GB_symbol" }, { "symbols", selected } });
        }

        private Dictionary<string, object> PlaceTrialMotor(ProjectManager pm, Project[] projects)
        {
            string trialPath = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            Project trial = null;
            foreach (Project p in projects)
                if (String.Equals(p.ProjectLinkFilePath, trialPath, StringComparison.OrdinalIgnoreCase)) trial = p;
            if (trial == null)
            {
                if (!File.Exists(trialPath)) return Error("TRIAL_NOT_FOUND", "Fixed disposable trial project does not exist");
                pm.LockProjectByDefault = true;
                try { trial = pm.OpenProject(trialPath); }
                catch (Exception ex) { return Error("TRIAL_OPEN_FAILED", ex.Message); }
            }
            Page target = null;
            foreach (Page page in trial.Pages)
                if (page.IdentifyingName == "/4") target = page;
            if (target == null) return Error("PAGE_NOT_FOUND", "Trial page /4 does not exist");
            foreach (Function existing in target.Functions)
                if (existing.VisibleName == "M1")
                {
                    if (existing.SymbolVariant == null || existing.SymbolVariant.SymbolName != "M3")
                        return Error("OBJECT_AMBIGUOUS", "M1 exists with an unexpected symbol");
                    return Ok(new Dictionary<string, object> { { "page", target.IdentifyingName },
                        { "function", existing.VisibleName }, { "already_present", true } });
                }
            try
            {
                trial.LockAllObjects();
                SymbolLibrary library = new SymbolLibrary(trial, "GB_symbol");
                Symbol symbol = new Symbol(library, "M3");
                SymbolVariant variant = new SymbolVariant();
                variant.Initialize(symbol, 0);
                Function motor = new Function();
                motor.Create(target, variant);
                motor.Name = "M1";
                motor.VisibleName = "M1";
                motor.Location = new PointD(100.0, 100.0);
                foreach (Function readback in target.Functions)
                    if (readback.VisibleName == "M1")
                        return Ok(new Dictionary<string, object> { { "page", target.IdentifyingName },
                        { "function", readback.VisibleName }, { "symbol_library", "GB_symbol" },
                            { "symbol", "M3" }, { "native_function_readback", true } });
                return Error("PARTIAL_NATIVE_WRITE", "Motor function inserted but readback did not find it");
            }
            catch (Exception ex) { return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message); }
        }

        private Dictionary<string, object> PrepareTrialPages(ProjectManager pm, Project[] projects)
        {
            // Fixed, disposable trial only. A model-supplied path or arbitrary project is never accepted.
            string destination = RuntimePath(@"workspace\motor_forward_reverse_trial.elk");
            string template = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                @"EPLAN\O_Data\Electric P8 Data\2.9.4\Templates\EPLAN\GB_bas001.zw9");
            if (!File.Exists(template)) return Error("TEMPLATE_NOT_FOUND", "Installed GB base template missing");
            Directory.CreateDirectory(Path.GetDirectoryName(destination));
            if (File.Exists(destination) || Directory.Exists(Path.ChangeExtension(destination, ".edb")))
                return Error("TRIAL_ALREADY_EXISTS", "Trial exists; no overwrite or implicit retry");
            try
            {
                Project trial = pm.CreateProject(destination, template);
                if (trial == null) return Error("CREATE_UNKNOWN", "CreateProject returned null; inspect workspace");
                for (int counter = 1; counter <= 9; counter++)
                {
                    PagePropertyList props = new PagePropertyList();
                    props.PAGE_COUNTER = counter;
                    Page page = new Page();
                    page.Create(trial, DocumentTypeManager.DocumentType.Circuit, props);
                }
                var pageNames = new List<string>();
                foreach (Page page in trial.Pages) pageNames.Add(page.IdentifyingName);
                if (pageNames.Count < 9)
                    return Error("PARTIAL_NATIVE_WRITE", "Trial created but fewer than 9 pages read back");
                return Ok(new Dictionary<string, object> { { "trial_project", trial.ProjectLinkFilePath },
                    { "pages", pageNames }, { "write_scope", "disposable_trial_only" } });
            }
            catch (Exception ex)
            {
                return Error("PARTIAL_OR_FAILED_NATIVE_WRITE", ex.Message + "; inspect disposable trial workspace");
            }
        }

        private static byte[] ReadExact(Stream stream, int count)
        {
            byte[] bytes = new byte[count];
            int read = 0;
            while (read < count)
            {
                int n = stream.Read(bytes, read, count - read);
                if (n <= 0) throw new EndOfStreamException();
                read += n;
            }
            return bytes;
        }

        private static Dictionary<string, object> Ok(object data)
        {
            return new Dictionary<string, object> { { "ok", true }, { "data", data }, { "error", null } };
        }
        private static Dictionary<string, object> Error(string code, string message)
        {
            return new Dictionary<string, object> { { "ok", false }, { "data", null },
                { "error", new Dictionary<string, object> { { "code", code }, { "message", message } } } };
        }
    }
}
