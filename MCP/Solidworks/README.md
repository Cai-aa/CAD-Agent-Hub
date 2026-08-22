# SolidWorks Agent MCP

面向 Codex、Claude、Cursor 等 MCP 客户端的本地 SolidWorks 交互建模服务器。

The server supports fast incremental edits on the active document as well as native parametric part creation.

```text
Skill / AI planner
  -> high-level part tool or incremental edit
  -> serialized STA COM executor
  -> native SolidWorks sketches and features
  -> dirty-feature rebuild; explicit save when requested
```

## 当前能力 / Capabilities

- 附着现有 SolidWorks，或显式启动新实例
- 新建、打开、保存和导出文档
- 原生二维草图：直线、圆、圆弧、样条、多段线
- 原生凸台拉伸、切除拉伸
- 两基准面交线参考轴
- 原生圆周阵列
- 基于方向、半径和 Z 高度的边线筛选
- 原生边线圆角和倒角
- Feature Graph 编译与事务执行
- 标准渐开线直齿圆柱齿轮事务
- 特征树命名、重建和保存结果检查
- 原位修改尺寸和单个特征参数
- 追加或替换已有草图
- 删除特征、移动回退棒
- 查询特征父子关系、面、边和草图关系
- 使用持久引用令牌继续选择面/边并添加圆角或倒角
- 高层参数化零件：方块、圆柱、管、法兰、阶梯轴

## 交互性能模式 / Interactive performance mode

0.4 默认使用交互模式：

- 不再关闭或遍历其他打开文档
- 不再默认执行完整特征树审计
- 使用 `EditRebuild3` 只重建脏特征，不再默认 `ForceRebuild3`
- 不再默认重绘和 Zoom to Fit
- 批量草图创建时启用 `AddToDB`、关闭即时显示和自动求解，结束后恢复
- 前一个 COM 操作仍在运行时，新操作立即返回 busy，不会继续堆积队列
- 尺寸、草图和特征编辑不自动保存；需要时显式调用 `solidworks_save_active`

如需旧版严格验证行为，可设置：

```powershell
$env:SOLIDWORKS_INTERACTIVE_MODE = 'false'
$env:SOLIDWORKS_SINGLE_DOCUMENT_MODE = 'true'
$env:SOLIDWORKS_VERIFY_FEATURE_TREE = 'true'
$env:SOLIDWORKS_REDRAW_AFTER_OPERATION = 'true'
```

## MCP 工具 / Tools

- `solidworks_health_check`
- `solidworks_operation_status`
- `solidworks_connect`
- `solidworks_list_documents`
- `solidworks_activate_document`
- `solidworks_get_bounding_box`
- `solidworks_get_mass_properties`
- `solidworks_rebuild_diagnostics`
- `solidworks_capture_view`
- `solidworks_list_configurations`
- `solidworks_activate_configuration`
- `solidworks_create_configuration`
- `solidworks_get_custom_properties`
- `solidworks_set_custom_properties`
- `solidworks_list_material_databases`
- `solidworks_get_material`
- `solidworks_assign_material`
- `solidworks_create_part`
- `solidworks_open_document`
- `solidworks_save_active`
- `solidworks_export_active`
- `solidworks_inspect_active`
- `solidworks_set_dimension`
- `solidworks_set_feature_parameter`
- `solidworks_edit_sketch`
- `solidworks_delete_feature`
- `solidworks_rollback`
- `solidworks_inspect_relations`
- `solidworks_select_references`
- `solidworks_add_edge_feature`
- `solidworks_create_parametric_part`
- `solidworks_compile_feature_graph`
- `solidworks_execute_feature_graph`
- `solidworks_create_involute_spur_gear`
- `solidworks_create_spur_gear`（旧版概念直边齿轮，仅兼容保留）

## 模型检查与取证 / Model inspection and evidence

首批检查工具覆盖打开文档、包围盒、质量属性、重建状态和视图截图。读取工具不会保存或关闭用户文档；
`solidworks_activate_document` 只接受当前已打开文档的精确标题。

The inspection tools cover open documents, bounding boxes, mass properties,
rebuild state, and viewport evidence. Read operations do not save or close user
documents. `solidworks_activate_document` accepts only the exact title of an
already-open document.

读取当前零件或装配体包围盒：

```json
{
  "include_hidden": true
}
```

只读检查重建状态：

```json
{
  "perform_rebuild": false,
  "full_rebuild": false
}
```

保存当前模型视图；输出必须为 BMP，默认不会覆盖已有文件：

```json
{
  "output_path": "C:\\path\\to\\exports\\solidworks_view.bmp",
  "width": 1600,
  "height": 900,
  "fit_view": true,
  "overwrite": false
}
```

## 材料、配置与属性 / Materials, configurations, and properties

第二阶段工具支持列出、创建和切换配置，读取或批量写入文档级/配置级自定义属性，
以及从 SolidWorks 已配置的 `.sldmat` 数据库读取和分配材料。所有写操作只修改当前
内存文档，不会自动保存；确认结果后显式调用 `solidworks_save_active`。

The second-stage tools list, create, and activate configurations; read or batch
upsert document/configuration custom properties; and assign materials from an
existing SolidWorks `.sldmat` database. Mutations do not auto-save. Call
`solidworks_save_active` explicitly after verification.

创建并激活一个配置：

```json
{
  "configuration_name": "Inspection",
  "comment": "QA inspection state",
  "alternate_name": "INSPECT",
  "activate": true
}
```

批量写入文档级属性；传入 `configuration_name` 可改为配置级属性：

```json
{
  "properties": {
    "PartNumber": "SW-MCP-001",
    "Revision": 2,
    "Released": true
  }
}
```

材料分配使用 `solidworks_list_material_databases` 返回的精确数据库路径：

```json
{
  "database_path": "C:\\path\\to\\solidworks materials.sldmat",
  "material_name": "Plain Carbon Steel",
  "configuration_name": "Inspection",
  "rebuild": true
}
```

## 增量编辑示例 / Incremental editing

修改拉伸深度，不重新创建零件：

```json
{
  "dimension_name": "D1@Boss-Extrude1",
  "value": 35,
  "unit": "mm"
}
```

替换已有草图：

```json
{
  "sketch_name": "Sketch1",
  "mode": "replace",
  "entities": [
    {
      "kind": "polyline",
      "closed": true,
      "points": [[-30, -20], [30, -20], [30, 20], [-30, 20]]
    }
  ]
}
```

查询 `solidworks_inspect_relations` 后，可把返回的边 `reference_token` 传给
`solidworks_add_edge_feature`，在不重新定位几何的情况下添加圆角或倒角。

## 高层参数化零件 / High-level parts

```json
{
  "part_type": "flange",
  "output_path": "E:\\exports\\flange.sldprt",
  "parameters": {
    "outer_diameter_mm": 120,
    "bore_diameter_mm": 40,
    "thickness_mm": 12,
    "bolt_circle_diameter_mm": 90,
    "bolt_hole_diameter_mm": 10,
    "bolt_count": 6
  }
}
```

支持的 `part_type`：`block`、`cylinder`、`tube`、`flange`、`stepped_shaft`。

## 原生渐开线齿轮 / Native involute gear

```json
{
  "output_path": "E:\\exports\\gear_m2_z20.sldprt",
  "module_mm": 2,
  "tooth_count": 20,
  "pressure_angle_deg": 20,
  "thickness_mm": 10,
  "bore_diameter_mm": 10,
  "root_fillet_mm": 0.45,
  "tip_chamfer_mm": 0.25
}
```

生成的原生特征树：

```text
GearBlankSketch
GearBlank
GearAxis
InvoluteToothSketch
ToothBoss
ToothCircularPattern
BoreSketch
BoreCut
RootFillet
TipChamfer
```

齿面点由渐开线方程生成，通过 SolidWorks 原生草图样条连接；齿坯、阵列、孔、圆角和倒角都是独立可编辑特征，不经过 STEP 导入。

## Feature Graph

`solidworks_execute_feature_graph` 接受受约束的 JSON 图。完整 schema 位于 `schemas/feature-graph.schema.json`。

```json
{
  "version": "1.0",
  "features": [
    {"name": "Part", "kind": "new_part"},
    {
      "name": "CylinderSketch",
      "kind": "sketch",
      "plane": "Front Plane",
      "entities": [{"kind": "circle", "center": [0, 0], "radius_mm": 25}]
    },
    {
      "name": "CylinderBoss",
      "kind": "boss_extrude",
      "sketch": "CylinderSketch",
      "depth_mm": 50
    }
  ]
}
```

所有数值输入使用毫米和角度；执行层进入 SolidWorks API 前统一转换为米和弧度。

## 安装 / Install

兼容 MCP Python SDK 1.x 与 2.x。SDK 2.x 使用公开的 `mcp.server.MCPServer`，
SDK 1.x 自动回退到 `mcp.server.fastmcp.FastMCP`。

使用已安装依赖的 Python 环境：

```powershell
$swPython = 'python'
& $swPython -m pip install -e .
```

注册到 Codex：

```powershell
codex mcp add solidworks-agent -- `
  'python' `
  '-m' 'solidworks_mcp.server'
```

SolidWorks 和 MCP 必须运行在相同 Windows 用户及相同权限级别。默认只附着现有实例；只有 `start_if_missing=true` 才会启动新的 SolidWorks。

## 验证 / Verification

```powershell
$swPython = 'python'
& $swPython -m compileall src tests
& $swPython -m unittest discover -s tests -v
```

单元测试验证契约、依赖引用、渐开线尺寸和预期特征树。新 COM 特征还必须在真实 SolidWorks 会话中创建 `.sldprt` 并检查特征树后，才视为完成实机验证。
