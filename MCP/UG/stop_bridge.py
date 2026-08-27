#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop the repaired in-NX bridge from an external Python process."""

from __future__ import annotations

import json

from nx_bridge_client import BridgeError, NXBridgeClient


def main() -> int:
    client = NXBridgeClient(timeout=10.0)
    try:
        result = client.request("stop")
    except BridgeError as exc:
        print("FAILED: %s" % exc)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
