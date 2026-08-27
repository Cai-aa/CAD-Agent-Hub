# -*- coding: utf-8 -*-
"""Play once in NX to load the non-blocking .NET remoting bridge."""

from __future__ import print_function

import os

import NXOpen


def _bridge_dir():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        here = ""
    if here and os.path.exists(
        os.path.join(here, "dotnet_bridge", "bin", "NXMcPRemotingServer.dll")
    ):
        return here
    configured = os.environ.get("NX_MCP_HOME", "").strip()
    if configured and os.path.exists(
        os.path.join(
            configured, "dotnet_bridge", "bin", "NXMcPRemotingServer.dll"
        )
    ):
        return configured
    raise RuntimeError(
        "Cannot locate NXMcPRemotingServer.dll. Run "
        "dotnet_bridge\\build_bridge.ps1 first or set NX_MCP_HOME."
    )


def main(args=None):
    bridge_dir = _bridge_dir()
    library = os.path.join(
        bridge_dir, "dotnet_bridge", "bin", "NXMcPRemotingServer.dll"
    )
    session = NXOpen.Session.GetSession()
    session.Execute(library, "NXMcPRemotingServer", "Start", [])


if __name__ == "__main__":
    main()
