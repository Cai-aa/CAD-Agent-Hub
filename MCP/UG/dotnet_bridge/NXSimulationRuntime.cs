using System;
using System.Collections;
using System.Collections.Generic;
using System.Web.Script.Serialization;

using NXOpen;
using NXOpen.CAM;
using NXOpen.SIM;

namespace NXMcP
{
    // Runs inside the NX AppDomain so the control panel survives independent
    // MCP requests. All geometry/readiness gates remain in nx_remote_ops.py.
    public static class SimulationRuntime
    {
        private static readonly object Sync = new object();
        private static IsvControlPanelBuilder Panel;
        private static string Status = "idle";
        private static Dictionary<string, object> Options;
        private static List<string> OperationNames;

        private static bool Bool(IDictionary<string, object> values, string name, bool fallback)
        {
            object raw;
            return values.TryGetValue(name, out raw) ? Convert.ToBoolean(raw) : fallback;
        }

        private static int Int(IDictionary<string, object> values, string name, int fallback)
        {
            object raw;
            return values.TryGetValue(name, out raw) ? Convert.ToInt32(raw) : fallback;
        }

        private static List<string> Strings(IDictionary<string, object> values, string name)
        {
            object raw;
            List<string> result = new List<string>();
            if (!values.TryGetValue(name, out raw) || raw == null)
            {
                return result;
            }
            IEnumerable sequence = raw as IEnumerable;
            if (sequence == null || raw is string)
            {
                throw new ArgumentException(name + " must be an array");
            }
            foreach (object item in sequence)
            {
                result.Add(Convert.ToString(item));
            }
            return result;
        }

        private static Dictionary<string, object> ConfigureOptions(
            SimulationOptionsBuilder options,
            IDictionary<string, object> parameters
        )
        {
            bool materialRemoval = Bool(parameters, "material_removal", true);
            options.SimulationDisplay = SimulationOptionsBuilder.SimulationDisplayMode.All;
            options.AnimationAccuracy = SimulationOptionsBuilder.Accuracy.Fine;
            options.DisplayStationary = SimulationOptionsBuilder.Stationary.Part;
            options.EnableMachineCollision = true;
            options.CheckLimitViolation = true;
            options.CheckToolHolderIpw = true;
            options.CheckToolHolderGougeCheck = true;
            options.ToolPartCollision = true;
            options.ToolIpwCollision = true;
            options.StopOnCollision = true;
            options.StopOnLimitViolation = true;
            options.EnableMaterialRemoval = materialRemoval;
            options.DisplayIpw = materialRemoval;
            options.IpwUpdate = SimulationOptionsBuilder.IpwUpdateMode.MotionBased;
            options.IpwResolution = SimulationOptionsBuilder.Resolution.Fine;
            options.StockSetting = SimulationOptionsBuilder.StockType.Automatic;
            return new Dictionary<string, object>
            {
                {"collision_detection", true},
                {"machine_collision", true},
                {"limit_check", true},
                {"tool_holder_check", true},
                {"tool_part_collision", true},
                {"tool_ipw_collision", true},
                {"stop_on_collision", true},
                {"stop_on_limit_violation", true},
                {"stop_on_rapid_through_ipw", true},
                {"rapid_through_ipw_stop_source", "stop_on_collision"},
                {"material_removal", materialRemoval},
                {"ipw_resolution", "fine"},
                {"tool_shape", "session_customer_default"},
            };
        }

        private static Dictionary<string, object> Start(IDictionary<string, object> parameters)
        {
            if (Panel != null)
            {
                throw new InvalidOperationException(
                    "An NX machine simulation is already active; stop it before starting another."
                );
            }
            int speed = Int(parameters, "speed", 25);
            if (speed < 1 || speed > 100)
            {
                throw new ArgumentOutOfRangeException("speed", "speed must be between 1 and 100");
            }
            List<string> names = Strings(parameters, "operation_names");
            if (names.Count == 0)
            {
                throw new ArgumentException("operation_names must identify at least one operation");
            }
            Session session = Session.GetSession();
            Part work = session.Parts.Work;
            if (work == null || work.CAMSetup == null)
            {
                throw new InvalidOperationException("The active work part has no CAM setup");
            }
            CAMSetup setup = work.CAMSetup;
            List<CAMObject> drivers = new List<CAMObject>();
            foreach (string name in names)
            {
                NXOpen.CAM.Operation operation = setup.CAMOperationCollection.FindObject(name);
                if (operation == null || !operation.AskPathExists())
                {
                    throw new InvalidOperationException(
                        "Every selected operation must own a generated toolpath"
                    );
                }
                drivers.Add(operation);
            }
            IsvControlPanelBuilder created = null;
            try
            {
                created = work.KinematicConfigurator.CreateIsvControlPanelBuilder(
                    IsvControlPanelBuilder.VisualizationType.ToolPathSimulation,
                    drivers.ToArray()
                );
                if (created == null)
                {
                    throw new InvalidOperationException("NX did not create a simulation control panel");
                }
                Dictionary<string, object> configured = ConfigureOptions(
                    created.SimulationOptionsBuilder, parameters
                );
                created.SetVisualization(IsvControlPanelBuilder.VisualizationType.ToolPathSimulation);
                created.SetSingleStep(IsvControlPanelBuilder.SingleStepType.Move);
                created.SetShowToolPath(Bool(parameters, "show_toolpath", true));
                created.SetShowToolTrace(Bool(parameters, "show_tool_trace", false));
                created.SetSpeed(speed);
                created.ApplySimulationOptions();
                created.ResetMachine();
                Panel = created;
                Options = configured;
                OperationNames = names;
                Status = "prepared";
                bool play = Bool(parameters, "play_immediately", true);
                if (play)
                {
                    Panel.PlayForward();
                    Status = "started";
                }
                return new Dictionary<string, object>
                {
                    {"ok", true},
                    {"simulation_prepared", true},
                    {"simulation_started", play},
                    {"status", Status},
                    {"operation_names", OperationNames},
                    {"speed", speed},
                    {"options", Options},
                    {"runtime", "nx_appdomain"},
                    {"production_nc_certified", false},
                };
            }
            catch
            {
                if (created != null && !Object.ReferenceEquals(created, Panel))
                {
                    created.Destroy();
                }
                throw;
            }
        }

        private static Dictionary<string, object> Inspect()
        {
            Dictionary<string, object> result = new Dictionary<string, object>
            {
                {"ok", true},
                {"active_panel_present", Panel != null},
                {"status", Status},
                {"operation_names", OperationNames ?? new List<string>()},
                {"options", Options ?? new Dictionary<string, object>()},
                {"machine_time", null},
                {"cycle_time_ms", null},
                {"vnc_status", null},
                {"runtime", "nx_appdomain"},
                {"production_nc_certified", false},
            };
            if (Panel != null)
            {
                try { result["machine_time"] = Panel.MachineTime; } catch { }
                try { result["cycle_time_ms"] = Panel.MachineControlGetCycleTime(); } catch { }
                try { result["vnc_status"] = Panel.VncStatus.ToString(); } catch { }
            }
            return result;
        }

        private static Dictionary<string, object> Stop(IDictionary<string, object> parameters)
        {
            bool release = Bool(parameters, "release", true);
            bool stopped = false;
            if (Panel != null)
            {
                Panel.Stop();
                stopped = true;
                Status = "stopped";
                if (release)
                {
                    Panel.Destroy();
                    Panel = null;
                    Options = null;
                    OperationNames = null;
                    Status = "idle";
                }
            }
            return new Dictionary<string, object>
            {
                {"ok", true},
                {"stopped", stopped},
                {"released", stopped && release},
                {"status", Status},
                {"runtime", "nx_appdomain"},
                {"production_nc_certified", false},
            };
        }

        public static string Handle(string requestJson)
        {
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            Dictionary<string, object> request = null;
            string requestId = null;
            try
            {
                request = serializer.Deserialize<Dictionary<string, object>>(requestJson);
                requestId = Convert.ToString(request["id"]);
                string method = Convert.ToString(request["method"]);
                IDictionary<string, object> parameters =
                    request.ContainsKey("params") && request["params"] != null
                    ? (IDictionary<string, object>)request["params"]
                    : new Dictionary<string, object>();
                Dictionary<string, object> result;
                lock (Sync)
                {
                    if (method == "start_machine_simulation_with_collision_stop")
                    {
                        result = Start(parameters);
                    }
                    else if (method == "inspect_active_machine_simulation")
                    {
                        result = Inspect();
                    }
                    else if (method == "stop_active_machine_simulation")
                    {
                        result = Stop(parameters);
                    }
                    else
                    {
                        throw new ArgumentException("Unknown simulation runtime method: " + method);
                    }
                }
                return serializer.Serialize(new Dictionary<string, object>
                {
                    {"id", requestId}, {"ok", true}, {"result", result}
                });
            }
            catch (Exception ex)
            {
                NXException nx = ex as NXException;
                Dictionary<string, object> error = new Dictionary<string, object>
                {
                    {"type", ex.GetType().FullName},
                    {"message", ex.Message},
                    {"error_code", nx == null ? null : (object)nx.ErrorCode},
                };
                return serializer.Serialize(new Dictionary<string, object>
                {
                    {"id", requestId}, {"ok", false}, {"error", error}
                });
            }
        }
    }
}

// NX Session.Execute resolves non-namespaced C# entry classes most reliably.
public class NXSimulationRuntime
{
    public static string Handle(string requestJson)
    {
        return NXMcP.SimulationRuntime.Handle(requestJson);
    }

    public static int GetUnloadOption(string dummy)
    {
        return Convert.ToInt32(Session.LibraryUnloadOption.AtTermination);
    }
}
