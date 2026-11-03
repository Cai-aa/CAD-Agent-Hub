"""Isolated 0.5 integrity acceptance through the real stdio MCP, not mocks."""

from __future__ import annotations
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(output: Path):
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(source / "src"),
        "SOLIDWORKS_OPERATION_JOURNAL": str(output / "operations.sqlite3"),
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "solidworks_mcp.server"],
        cwd=str(source),
        env=env,
    )
    evidence = {"status": "RUNNING", "checks": [], "artifacts": []}

    def persist():
        (output / "acceptance.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def checked(name, data=None):
        evidence["checks"].append({"name": name, "passed": True, "evidence": data})
        persist()

    try:
        with (output / "server-stderr.log").open("w", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    evidence["tool_count"] = len(tools.tools)

                    async def call(name, args=None, error=None):
                        args = dict(args or {})
                        if "request_id" in next(
                            item for item in tools.tools if item.name == name
                        ).inputSchema.get("properties", {}):
                            args.setdefault("request_id", str(time.time_ns()))
                        print("Calling " + name, flush=True)
                        response = await session.call_tool(name, args)
                        text = "\n".join(
                            item.text
                            for item in response.content
                            if item.type == "text"
                        )
                        if error:
                            assert response.isError and error in text, text
                            return {"isError": True, "text": text}
                        assert not response.isError, text
                        decoded = json.loads(text)
                        return decoded.get("result", decoded)

                    health = await call("solidworks_health_check")
                    assert health["part_template_exists"]
                    await call("solidworks_connect", {"start_if_missing": True})
                    initial = await call("solidworks_list_documents")
                    evidence["initial_documents"] = initial
                    specs = [
                        (
                            "cylinder",
                            {"diameter_mm": 20, "length_mm": 20},
                            math.pi * 0.01**2 * 0.02,
                        ),
                        (
                            "tube",
                            {
                                "outer_diameter_mm": 30,
                                "inner_diameter_mm": 20,
                                "length_mm": 40,
                            },
                            math.pi / 4 * (0.03**2 - 0.02**2) * 0.04,
                        ),
                        (
                            "block",
                            {"length_mm": 30, "width_mm": 20, "height_mm": 10},
                            0.03 * 0.02 * 0.01,
                        ),
                    ]
                    parts = []
                    for kind, parameters, expected in specs:
                        target = output / (kind + "_" + output.name + ".sldprt")
                        result = await call(
                            "solidworks_create_parametric_part",
                            {
                                "part_type": kind,
                                "parameters": parameters,
                                "output_path": str(target),
                            },
                        )
                        assert (
                            result["feature_tree_verified"]
                            and result["verification"]["analytic_volume_verified"]
                        )
                        mass = await call("solidworks_get_mass_properties")
                        assert math.isclose(mass["volume_m3"], expected, rel_tol=1e-5)
                        assert target.stat().st_size > 0
                        info = await call("solidworks_inspect_active")
                        parts.append(
                            {
                                "token": result["document_token"],
                                "title": info["title"],
                                "path": str(target),
                            }
                        )
                        evidence["artifacts"].append(str(target))
                        checked(
                            "native_" + kind,
                            {
                                "bytes": target.stat().st_size,
                                "volume_m3": mass["volume_m3"],
                            },
                        )
                    # Block is active while the old cylinder token is supplied.
                    result = await call(
                        "solidworks_set_dimension",
                        {
                            "dimension_name": "D1@CylinderBoss",
                            "value": 30,
                            "document_token": parts[0]["token"],
                        },
                        error="DOCUMENT_NOT_BOUND",
                    )
                    checked("wrong_document_refused", result)
                    await call(
                        "solidworks_activate_document", {"title": parts[0]["title"]}
                    )
                    binding = await call(
                        "solidworks_bind_document",
                        {"title": parts[0]["title"], "expected_path": parts[0]["path"]},
                    )
                    token = binding["document_token"]
                    request_id = "dimension-" + str(time.time_ns())
                    args = {
                        "dimension_name": "D1@CylinderBoss",
                        "value": 30,
                        "document_token": token,
                        "request_id": request_id,
                    }
                    edited = await call("solidworks_set_dimension", args)
                    assert edited["ok"]
                    replay = await call("solidworks_set_dimension", args)
                    assert replay["idempotent_replay"]
                    result = await call(
                        "solidworks_set_dimension",
                        {**args, "value": 35},
                        error="REQUEST_CONFLICT",
                    )
                    mass = await call("solidworks_get_mass_properties")
                    assert math.isclose(
                        mass["volume_m3"], math.pi * 0.01**2 * 0.03, rel_tol=1e-5
                    )
                    checked(
                        "dimension_readback_volume_and_idempotency",
                        {"volume_m3": mass["volume_m3"], "conflict": result},
                    )
                    edited_target = output / (
                        "cylinder_edited_" + output.name + ".sldprt"
                    )
                    await call(
                        "solidworks_save_active",
                        {"path": str(edited_target), "document_token": token},
                    )
                    evidence["artifacts"].append(str(edited_target))
                    before = edited_target.read_bytes()
                    result = await call(
                        "solidworks_save_active",
                        {"path": str(edited_target), "document_token": token},
                        error="already exists",
                    )
                    assert edited_target.read_bytes() == before
                    checked("overwrite_refused_original_preserved", result)
                    result = await call(
                        "solidworks_set_dimension",
                        {
                            "dimension_name": "MissingDimension@MissingFeature",
                            "value": 2,
                            "document_token": token,
                        },
                        error="MUTATION_FAILED",
                    )
                    checked("failed_mutation_reported_as_protocol_error", result)
                    result = await call(
                        "solidworks_set_dimension",
                        {
                            "dimension_name": "D1@CylinderBoss",
                            "value": 40,
                            "document_token": token,
                        },
                        error="RECOVERY_REQUIRED",
                    )
                    checked("subsequent_write_blocked", result)
                    status = await call(
                        "solidworks_operation_result", {"request_id": request_id}
                    )
                    assert status["state"] == "SUCCEEDED"
                    checked("durable_outcome_query", status)
                    result = await call(
                        "solidworks_reload_runtime", error="RELOAD_DISABLED"
                    )
                    checked("reload_disabled_in_code", result)
                    # No user documents are closed by this acceptance script.
                    evidence["status"] = "LIVE_INTEGRITY_VERIFIED"
    except BaseException as exc:
        evidence["status"], evidence["error"] = "FAILED", repr(exc)
        raise
    finally:
        persist()
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "checks": len(evidence["checks"]),
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()
    asyncio.run(main(arguments.output_dir.resolve()))
