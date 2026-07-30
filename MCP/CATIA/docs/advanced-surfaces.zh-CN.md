# 高级线框与曲面接口

高级曲面层是对 CATIA V5 `HybridShapeFactory`、`HybridShapeLoft`、
`HybridShapeSpline`、`HybridShapeAssemble`、`HybridShapeHealing`、
`ShapeFactory` 和 `SPAWorkbench` 的固定、强类型封装。它不开放任意 COM、
CATScript、VBA 或 Python 执行。

## 实时能力探测

在活动 CATPart 上先调用 `catia_surface_capabilities`。返回结果会列出当前安装版本
实际提供的 `HybridShapeFactory`、`ShapeFactory` 方法，以及 Automation 能返回的连续性
和质量检查范围。仅检测到安装文件不能证明 GSD/GSO 许可证可用。

## 工具分组

线框与参考几何：

- `catia_create_geometrical_set`
- `catia_create_3d_points`
- `catia_create_spline`
- `catia_create_offset_plane`
- `catia_create_connect_curve`

曲面创建和修复：

- `catia_create_loft`
- `catia_create_fill`
- `catia_join_surfaces`
- `catia_heal_surfaces`
- `catia_create_boundary`

实体转换：

- `catia_close_surface`
- `catia_thick_surface`

检查：

- `catia_check_surface_quality`

## 放样契约

`catia_create_loft` 接收两个或更多按顺序排列的截面。截面方向数组和闭合点数组若非空，
数量必须与截面一致。`coupling` 映射到 CATIA 原生 `SectionCoupling`：

| 值 | CATIA 耦合方式 |
|---|---|
| `ratio` | 曲线长度比例 |
| `tangency` | 切向不连续点 |
| `curvature` | 切向和曲率不连续点 |
| `vertices` | 对应顶点 |

引导线按照输入顺序加入。起止切向曲面提供 G1 边界连续。CATIA
`HybridShapeLoft` Automation 接口没有提供 G2 边界曲面开关；G2 要通过截面/引导
Spline 的曲率约束，或在适用位置使用 `catia_create_connect_curve` 建立。

`context="surface"` 创建曲面；`context="volume"` 请求 CATIA 的放样体环境，需要相应
GSO 许可证。

## 连续性范围

- Connect Curve：两端可分别设置 G0、G1、G2。
- Spline 对已有曲线的约束：G1、G2。
- Loft 边界：无切向曲面时为 G0，指定切向曲面时为 G1。
- Healing：G0、G1，与本机 V5 Automation 文档一致。

接口不会把无法实现的连续性静默降级。

## Join、Healing 与质量检查

Join 支持距离公差、角度公差、连通性、流形和简化控制。Healing 支持距离目标、
合并距离、切向角、锐边角和 G0/G1。

Fill 支持多条边界、可选支撑曲面和 G0/G1/G2 边界连续，可用于封闭 Loft 两端，再执行
Join 与 Close Surface。

`catia_check_surface_quality` 会实际执行：

- 对每个命名特征调用 `Part.UpdateObject`；
- 对适用几何调用 SPAWorkbench 测量；
- 对指定元素对计算最小距离；
- 返回 Join 的连通性、流形、偏差和角度模式。

本机 V5 Automation 契约没有提供可查询的交互式曲率梳结果，也没有提供可查询的
自相交诊断结果。接口会明确返回“不支持”，不会伪造检查通过。发布验收时仍需在
CATIA 交互式曲面分析命令中复核。

## 实时验证

CATIA 已打开时执行：

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python '.\scripts\probe_surfaces.py'
```

脚本会创建三个闭合三维 Spline、一个原生 HybridShapeLoft、边界和质量检查证据，并在
配置的工作区保存 `Surface_API_Probe.CATPart`。
