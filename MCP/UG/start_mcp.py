# -*- coding: utf-8 -*-
"""
START the NX MCP bridge - run this as an NX journal (Tools > Journal > Play),
or bind it to a "Start MCP" ribbon button.

It imports nx_mcp_plugin as a real module so the bridge lives in sys.modules and
its background threads + state survive after this journal finishes. Importing it
again later (e.g. from stop) returns the SAME live module.
"""

from __future__ import print_function

import os
import sys


def _bridge_dir():
    # Prefer the folder this journal lives in; fall back to NX_MCP_HOME.
    here = None
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        pass
    if here and os.path.exists(os.path.join(here, "nx_mcp_plugin.py")):
        return here
    env = os.environ.get("NX_MCP_HOME", "").strip()
    if env and os.path.exists(os.path.join(env, "nx_mcp_plugin.py")):
        return env
    raise RuntimeError(
        "Cannot locate nx_mcp_plugin.py. Set NX_MCP_HOME to the MCP/UG directory."
    )


def main(args=None):
    bridge_dir = _bridge_dir()
    if bridge_dir not in sys.path:
        sys.path.insert(0, bridge_dir)
    import importlib
    import nx_mcp_plugin
    # Pick up code edits without restarting NX (safe: the bridge is stopped here).
    nx_mcp_plugin = importlib.reload(nx_mcp_plugin)
    # This BLOCKS (runs the cooperative socket + UI-pump loop) and does not
    # return until stopped. Do NOT add a "# nx: threaded" directive to this file.
    nx_mcp_plugin.serve_blocking()


if __name__ == "__main__":
    main()
