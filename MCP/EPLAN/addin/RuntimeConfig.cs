using System;
using System.IO;
using System.Diagnostics;

namespace Codex.EplAddin
{
    public sealed partial class CodexBridge
    {
        private static string RuntimePath(string relative)
        {
            string configured = Environment.GetEnvironmentVariable("EPLAN_MCP_WORKSPACE");
            if (String.IsNullOrWhiteSpace(configured) || !Path.IsPathRooted(configured) || configured.StartsWith(@"\\"))
                throw new InvalidOperationException("Configure an absolute local EPLAN_MCP_WORKSPACE before starting a trial instance");
            string root = Path.GetFullPath(configured).TrimEnd(Path.DirectorySeparatorChar);
            string path = Path.GetFullPath(Path.Combine(root, relative));
            if (!String.Equals(root,path,StringComparison.OrdinalIgnoreCase) &&
                !path.StartsWith(root + Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Runtime path leaves the configured workspace");
            return path;
        }

        private static string NativeBuild()
        {
            FileVersionInfo v = FileVersionInfo.GetVersionInfo(Process.GetCurrentProcess().MainModule.FileName);
            return String.Format("{0}.{1}.{2}.{3}", v.FileMajorPart,v.FileMinorPart,v.FileBuildPart,v.FilePrivatePart);
        }
    }
}
