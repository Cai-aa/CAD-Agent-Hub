using System;
using System.IO;
using System.Reflection;
using System.Text;

public class NXRemoteClient
{
    // Force the NXOpen.Utilities exception assembly into the client AppDomain so
    // SOAP remoting can deserialize NX exceptions raised by Session.Execute.
    private static readonly Type NXExceptionType = typeof(NXOpen.NXException);

    private static string GetArgument(string[] args, string name, string fallback)
    {
        for (int i = 0; i + 1 < args.Length; ++i)
        {
            if (String.Equals(args[i], name, StringComparison.OrdinalIgnoreCase))
            {
                return args[i + 1];
            }
        }
        return fallback;
    }

    private static string DefaultNXOpenPath()
    {
        string root = Environment.GetEnvironmentVariable("UGII_BASE_DIR");
        if (String.IsNullOrEmpty(root))
        {
            throw new InvalidOperationException("UGII_BASE_DIR is not set; pass --nxopen explicitly");
        }
        return Path.Combine(root, "NXBIN", "managed", "NXOpen.dll");
    }

    public static int Main(string[] args)
    {
        Console.InputEncoding = Encoding.UTF8;
        Console.OutputEncoding = new UTF8Encoding(false);
        try
        {
            string url = GetArgument(
                args,
                "--url",
                "http://127.0.0.1:48161/NXOpenSession"
            );
            string nxOpenPath = GetArgument(args, "--nxopen", null);
            if (String.IsNullOrEmpty(nxOpenPath))
            {
                nxOpenPath = DefaultNXOpenPath();
            }
            string operationsPath = GetArgument(args, "--ops", null);
            if (String.IsNullOrEmpty(operationsPath))
            {
                throw new ArgumentException("--ops must point to nx_remote_ops.py");
            }
            string className = GetArgument(args, "--class", null);
            string methodName = GetArgument(args, "--method", "handle");

            string requestJson = Console.In.ReadToEnd().Trim();
            if (requestJson.Length == 0)
            {
                throw new InvalidOperationException("stdin did not contain a JSON request");
            }

            Assembly nxOpen = Assembly.LoadFrom(nxOpenPath);
            string nxUtilitiesPath = Path.Combine(
                Path.GetDirectoryName(nxOpenPath), "NXOpen.Utilities.dll"
            );
            if (File.Exists(nxUtilitiesPath))
            {
                Assembly.LoadFrom(nxUtilitiesPath);
            }
            Type sessionType = nxOpen.GetType("NXOpen.Session", true);
            object session = Activator.GetObject(sessionType, url);
            MethodInfo execute = sessionType.GetMethod(
                "Execute",
                new Type[] { typeof(string), typeof(string), typeof(string), typeof(object[]) }
            );
            if (execute == null)
            {
                throw new MissingMethodException("NXOpen.Session.Execute was not found");
            }

            object response = execute.Invoke(
                session,
                new object[] {
                    Path.GetFullPath(operationsPath),
                    className,
                    methodName,
                    new object[] { requestJson }
                }
            );
            if (!(response is string))
            {
                throw new InvalidOperationException(
                    "NX operation returned " + (response == null ? "null" : response.GetType().FullName)
                );
            }
            Console.Write((string)response);
            return 0;
        }
        catch (TargetInvocationException ex)
        {
            Exception actual = ex.InnerException ?? ex;
            Console.Error.WriteLine(actual.ToString());
            return 2;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            return 2;
        }
    }
}
