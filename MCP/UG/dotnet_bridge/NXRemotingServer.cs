using System;
using System.Collections;
using System.IO;
using System.Runtime.Remoting;
using System.Runtime.Remoting.Channels;
using System.Runtime.Remoting.Channels.Http;
using System.Runtime.Remoting.Lifetime;
using System.Runtime.Serialization.Formatters;
using System.Threading;

using NXOpen;

// Non-blocking in-process bootstrap based on Siemens' installed
// SampleNXOpenApplications/DotNet/RemotingExample. Main returns immediately;
// only the remoting channel runs on a worker thread.
public class NXMcPRemotingServer
{
    private static readonly object Sync = new object();
    private static readonly ManualResetEvent StopEvent = new ManualResetEvent(false);
    private static Thread serverThread;
    private static HttpChannel channel;
    private static Session session;
    private static volatile bool started;

    private static string LogPath
    {
        get { return Path.Combine(Path.GetTempPath(), "nx_mcp_remoting_server.log"); }
    }

    private static void Log(string message)
    {
        try
        {
            lock (Sync)
            {
                File.AppendAllText(
                    LogPath,
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + message + Environment.NewLine
                );
            }
        }
        catch
        {
        }
    }

    public static void Main(string[] args)
    {
        Start();
    }

    // NX calls Startup automatically for .NET libraries found in a configured
    // startup directory (for example %UGII_USER_DIR%\startup).
    public static int Startup()
    {
        Start();
        return 0;
    }

    public static void Start()
    {
        lock (Sync)
        {
            if (started)
            {
                Log("Start ignored: server is already active");
                return;
            }

            // Siemens' sample explicitly obtains Session on NX's calling thread
            // before the remoting worker is created.
            session = Session.GetSession();
            StopEvent.Reset();
            serverThread = new Thread(new ThreadStart(Run));
            serverThread.Name = "NX-MCP-Remoting";
            serverThread.IsBackground = true;
            started = true;
            serverThread.Start();
            Log("Bootstrap returned without blocking NX");
        }
    }

    private static int GetPort()
    {
        string raw = Environment.GetEnvironmentVariable("NX_MCP_REMOTING_PORT");
        int port;
        if (!Int32.TryParse(raw, out port))
        {
            port = 48161;
        }
        if (port < 1 || port > 65535)
        {
            throw new InvalidOperationException("NX_MCP_REMOTING_PORT must be between 1 and 65535");
        }
        return port;
    }

    private static void Run()
    {
        try
        {
            LifetimeServices.LeaseTime = TimeSpan.FromDays(10000);

            SoapServerFormatterSinkProvider provider = new SoapServerFormatterSinkProvider();
            provider.TypeFilterLevel = TypeFilterLevel.Full;

            IDictionary properties = new Hashtable();
            properties["name"] = "nx-mcp-remoting";
            properties["port"] = GetPort();
            properties["bindTo"] = "127.0.0.1";

            channel = new HttpChannel(properties, null, provider);
            ChannelServices.RegisterChannel(channel, false);
            RemotingServices.Marshal(session, "NXOpenSession");
            Log("Ready on http://127.0.0.1:" + GetPort() + "/NXOpenSession pid=" +
                System.Diagnostics.Process.GetCurrentProcess().Id);

            StopEvent.WaitOne();
        }
        catch (Exception ex)
        {
            Log("Server error: " + ex);
        }
        finally
        {
            try
            {
                if (session != null)
                {
                    RemotingServices.Disconnect(session);
                }
            }
            catch
            {
            }
            try
            {
                if (channel != null)
                {
                    ChannelServices.UnregisterChannel(channel);
                }
            }
            catch
            {
            }
            channel = null;
            started = false;
            Log("Server stopped");
        }
    }

    public static int GetUnloadOption(string dummy)
    {
        return (int)Session.LibraryUnloadOption.AtTermination;
    }

    public static void UnloadLibrary(string dummy)
    {
        StopEvent.Set();
        Thread thread = serverThread;
        if (thread != null && thread.IsAlive)
        {
            thread.Join(5000);
        }
    }
}
