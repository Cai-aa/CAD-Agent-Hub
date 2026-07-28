# CAD Agent Hub

Windows-focused MCP servers, application bridges, engineering Skills, and reproducible modeling examples for AI-assisted CAD/CAE workflows.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

## Included projects

| Path | Purpose |
| --- | --- |
| [`MCP/CATIA`](MCP/CATIA) | CATIA V5 modeling and native Analysis MCP server |
| [`MCP/Solidworks`](MCP/Solidworks) | Stateful SolidWorks modeling MCP server |
| [`MCP/UG`](MCP/UG) | Siemens NX/UG MCP server and in-process bridge |
| [`fusion_electronics_write_bridge`](fusion_electronics_write_bridge) | Local Fusion Electronics write bridge |
| [`skills/ansys-structural-workbench`](skills/ansys-structural-workbench) | Quality-gated ANSYS Workbench structural-analysis Skill |
| [`models`](models) | Reproducible build123d/cadpy model source examples |
| [`fusion_starship_v3_builder.py`](fusion_starship_v3_builder.py) | Autodesk Fusion parametric modeling example |

Each MCP directory contains its own setup and validation instructions. These integrations require the corresponding proprietary CAD application and must generally run under the same Windows user and integrity level as that application.

## Repository scope

This repository intentionally contains source code, tests, schemas, portable configuration examples, and documentation only. Local workspaces, solver jobs, caches, logs, dependency copies, screenshots, and generated CAD binaries are excluded. Example paths such as `C:\path\to\CAD-Agent-Hub` must be replaced with the local clone path.

## Validation

Run each MCP project's documented unit tests before using it with a live CAD session. A successful COM/API call is not by itself proof that a model, mesh, drawing, or simulation result is correct; inspect the native application state and generated artifacts.
