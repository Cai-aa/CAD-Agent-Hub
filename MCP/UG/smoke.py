#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only by default smoke test for the live NX bridge."""

from __future__ import annotations

import argparse
import json

from nx_bridge_client import BridgeError, NXBridgeClient


def show(label: str, value: dict) -> None:
    print("\n=== %s ===" % label)
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create-block",
        action="store_true",
        help="also create a 100 x 60 x 40 block in the active work part",
    )
    args = parser.parse_args()
    client = NXBridgeClient()
    print("NX MCP smoke -> %s" % client.endpoint)
    try:
        show("ping", client.request("ping"))
        show("part_summary", client.request("part_summary", {"max_features": 20}))
        if args.create_block:
            show(
                "create_block",
                client.request(
                    "create_block",
                    {"length": 100.0, "width": 60.0, "height": 40.0},
                ),
            )
    except BridgeError as exc:
        print("\nFAILED: %s" % exc)
        return 1
    print("\nPASS: bridge and active NX work part responded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
