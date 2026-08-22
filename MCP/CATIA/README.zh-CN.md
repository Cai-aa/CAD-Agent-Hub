# CATIA Agent MCP

高级线框与曲面接口说明：
[docs/advanced-surfaces.zh-CN.md](docs/advanced-surfaces.zh-CN.md)。

防覆盖、临时文件验证和超时恢复：
[docs/safe-export.zh-CN.md](docs/safe-export.zh-CN.md)。

这是一个 Windows 本地 STDIO MCP Server，用于让 Codex/AI Agent 控制 CATIA V5 的原生建模和 CATIA 内部 Analysis/ELFINI 仿真。它不会调用 Abaqus、ANSYS、CalculiX 或其他第三方求解器。

## 已实现范围

- CATPart：草图、Pad、Pocket、参数、材料、更新、保存、导出和模型树检查。
- CATProduct：新建装配体、插入零部件和装配结构检查。
- CATAnalysis：导入零件/装配、工况、Solution、Analysis Set、载荷/约束实体、支撑绑定、Mesh Part、网格规格、CATIA 内部计算、结果图像/数据和 HTML 报告。
- 原生 GSD 线框/曲面：三维点、开闭 Spline、偏置平面、G0/G1/G2 Connect、
  HybridShapeLoft 截面/引导线/耦合/闭合点、Join、Healing、Boundary、
  Close Surface 和 Thick Surface。
- 共 53 个固定、带类型的 MCP 工具。
- 不开放任意 Python、CATScript、Shell 或任意 COM 方法执行。
- CATIA COM 调用集中到单个 STA 工作线程，支持请求 ID 幂等、忙碌拒绝和文件根目录边界。

本机验证目标是安装在 `G:\Program Files\Dassault Systemes\B33` 的 CATIA P3 V5-6R2023。代码会自动发现 CATEnv，不把这个安装位置写死在核心实现中。

## 多版本策略

- 目标基线：B28 / V5-6R2018 及以上。
- 本机验证版本：B33 / V5-6R2023。
- 更高版本继续保留完整工具面；服务器通过本机 TypeLib 和对象方法探测，只对实际缺失的操作做能力门控。
- B28 以前的版本不在正式适配范围。确需尝试时显式设置 `CATIA_MCP_ALLOW_LEGACY=true`。
- GPS/GAS/EST 等模块的 Analysis late type 不被压缩成最低版本公共子集；可通过通用但受控的 Set、Entity、Value、Support、Mesh、Image 接口使用当前版本已安装的高级能力。

安装目录中存在 DLL 或 TypeLib 不等于 GPS/GAS/EST 许可证可用。第一次真实许可证检查是创建并导入 `CATAnalysis` 文档。

## 启动和配置

当前机器可直接使用：

```powershell
& '.\scripts\run_server.ps1'
```

Codex 配置示例位于 [examples/codex_config.example.toml](examples/codex_config.example.toml)。安装其他 CATIA 版本时，将 `CATIA_MCP_ENV_NAME` 改为对应 CATEnv 文件名即可，例如：

```toml
CATIA_MCP_ENV_NAME = "CATIA_P3.V5-6R2023.B33"
CATIA_MCP_MIN_RELEASE_INDEX = "28"
```

服务器兼容 MCP SDK 1.x 和 2.x（`mcp>=1.7,<3`）：SDK 2.x 使用公开的
`MCPServer` API，仅在 SDK 1.x 下回退到旧版 `FastMCP` 导入。

CATIA 与 MCP 必须在相同 Windows 用户和相同权限级别下运行。如果一个以管理员权限启动、另一个不是，可能看得到 `CNEXT.exe`，却无法从 ROT 取得 `CATIA.Application`。

## 工具分组

建模与会话：

- `catia_health_check`、`catia_connect`、`catia_list_documents`
- `catia_create_part`、`catia_create_product`
- `catia_create_sketch`、`catia_add_pad`、`catia_add_pocket`
- `catia_create_parametric_part`、`catia_add_components`
- `catia_list_materials`、`catia_apply_material`
- `catia_list_parameters`、`catia_set_parameter`
- `catia_update_active`、`catia_inspect_active`
- `catia_save_active`、`catia_export_active`、`catia_capture_view`

`catia_export_active` 默认 `overwrite_policy="error"`。目标已存在时不会进入
CATIA，也不会弹出覆盖窗口。需要保留版本时使用 `versioned`；需要替换时使用
`replace`，工具会先导出并回读验证唯一临时文件，再执行文件系统替换。

`catia_add_pocket` 新增向后兼容的 `reverse=false` 参数。原点平面草图需要朝
草图法向另一侧的材料切除时，设置 `reverse=true`。返回结果会给出切除方向、
以 mm^3 表示的切除前后体积、`removed_volume_mm3` 和 `material_removed`；体积没有下降时返回
`status="no_material_removed"` 和警告，不再把无效切除伪装成已验证成功。

`catia_capture_view` 继续只接受 BMP，以保持 CATIA V5 Automation 的稳定兼容。
工具使用 `catCaptureFormatBMP`（数值 `4`），并在返回 `is_image=true` 前检查
文件头必须为 `BM`；CATIA 静默生成非图片内容时会返回错误。

CATIA 已运行时，可执行 `python .\scripts\validate_issue_fixes.py`，创建隔离测试
零件并同时验证反向 Pocket 的方向/体积和 BMP 文件头。产物写入 `workspace`，
脚本不会关闭用户已有文档。

CATIA 内部仿真：

- `catia_analysis_catalog`
- `catia_create_analysis_document`、`catia_inspect_analysis`
- `catia_add_analysis_case`、`catia_add_analysis_solution`
- `catia_run_analysis_transition`（保留高级模块的原生 Transition）
- `catia_add_analysis_set`、`catia_add_analysis_entity`
- `catia_set_analysis_entity_value`、`catia_bind_analysis_support`
- `catia_add_analysis_mesh_part`
- `catia_set_analysis_mesh_specification`、`catia_bind_analysis_mesh_support`
- `catia_compute_analysis`
- `catia_create_analysis_result_image`
- `catia_export_analysis_result_data`
- `catia_build_analysis_report`

## 推荐操作顺序

1. 调用 `catia_health_check`，确认选中的版本和 Analysis TypeLib。
2. 调用 `catia_connect`；默认只连接，不擅自启动新实例。
3. 使用小粒度原生特征建模，每个关键步骤后检查模型树。
4. 先分配具有力学属性的 CATIA 材料，再创建 CATAnalysis。
5. 导入零件/装配后检查 Model、Case、Set 和 Mesh Part。
6. 创建约束、载荷、网格与支撑，随后先执行 `mesh_only=true`。
7. 检查网格后再执行完整计算。
8. 创建结果图像、导出数值数据并生成 CATIA 原生报告。

`Compute` 返回只说明 CATIA 的 COM 调用已经返回，不代表物理模型正确。必须继续检查材料、单位、边界条件、网格、结果图像、位移/应力数据和报告。

## 本地验证命令

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python -m unittest discover -s '.\tests' -v
python -m compileall -q '.\src'
python '.\scripts\stdio_smoke.py'
python '.\scripts\probe_environment.py'
python '.\scripts\probe_live.py'
```

详细兼容性和架构说明见 [docs/compatibility-and-architecture.md](docs/compatibility-and-architecture.md)。
