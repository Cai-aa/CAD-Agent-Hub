# CAD Agent Hub

面向 Windows 的 CAD 智能体项目集合，包含 MCP Server、桌面应用桥接和可复现的参数化建模示例。

English documentation: [README.md](README.md)

## 包含内容

| 路径 | 用途 |
| --- | --- |
| [`MCP/CATIA`](MCP/CATIA) | CATIA V5 建模与原生 Analysis MCP Server |
| [`MCP/Solidworks`](MCP/Solidworks) | 有状态的 SolidWorks 建模 MCP Server |
| [`MCP/UG`](MCP/UG) | Siemens NX/UG MCP Server 与 NX 内桥接程序 |
| [`fusion_electronics_write_bridge`](fusion_electronics_write_bridge) | Fusion Electronics 本地写入桥 |
| [`models`](models) | 可复现的 build123d/cadpy 建模源码示例 |
| [`fusion_starship_v3_builder.py`](fusion_starship_v3_builder.py) | Autodesk Fusion 参数化建模示例 |

每个 MCP 子目录都提供独立的安装和验证说明。这些集成需要相应的商业 CAD 软件，并且通常要求 MCP 与 CAD 软件在同一 Windows 用户和同一权限级别下运行。

## 仓库边界

本仓库只保留源码、测试、Schema、可移植配置示例和文档。不会上传本机工作区、求解任务、缓存、日志、依赖副本、截图或生成的 CAD 二进制文件。文档中的 `C:\path\to\CAD-Agent-Hub` 等示例路径需要替换为实际克隆路径。

## 验证原则

连接真实 CAD 会话前，请先执行各 MCP 项目文档中的单元测试。COM/API 调用成功不等于模型、网格、工程图或仿真结果正确，仍需在原生软件中检查模型树、参数和生成产物。
