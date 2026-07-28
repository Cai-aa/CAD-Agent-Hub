# -*- coding: utf-8 -*-
"""
Stop helper.

NOTE: with the blocking design (serve_blocking), the start journal occupies the
NX journal runner, so you normally CANNOT play this from inside NX while the
bridge is running. Use the external `stop_mcp.py` instead - it connects over the
socket and sends a "stop" request, which breaks the serve loop.

This file is kept only for the rare case where the bridge module is imported but
not currently blocking; it calls stop_serving() directly.
"""

from __future__ import print_function

import sys


def main(args=None):
    mod = sys.modules.get("nx_mcp_plugin")
    if mod is None:
        print("nx_mcp_plugin is not loaded in this session. Use external stop_mcp.py.")
        return
    mod.stop_serving()
    print("stop_serving() signaled.")


if __name__ == "__main__":
    main()
