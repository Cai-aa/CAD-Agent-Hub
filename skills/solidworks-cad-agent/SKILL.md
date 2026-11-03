---
name: solidworks-cad-agent
description: Use the locally installed CAD-Agent-Hub SolidWorks MCP to inspect, create, and edit native SolidWorks parts on this Windows computer, including feature graphs and parametric gears.
---

# SolidWorks CAD Agent

This is a local Codex adaptation for Cai-aa/CAD-Agent-Hub commit
`339840b5f775e81d0b18519806ccb5e59885e2a6` with the local integrity and reusable modeling-rules patches.
It is not an upstream SolidWorks release or Skill.

MCP server: `solidworks-agent`.
Runtime: `<checkout>/MCP/Solidworks`.
Python: `<python-with-solidworks-agent-installed>`.
Source checkout: `<checkout>/MCP/Solidworks`.
The installed runtime is a separate pinned copy; edits to the checkout do not update it.

Use `solidworks_health_check` first. The machine uses SolidWorks 2024 templates,
configured through `SOLIDWORKS_PART_TEMPLATE` and `SOLIDWORKS_ASSEMBLY_TEMPLATE`.
Use `solidworks_connect(start_if_missing=false)` to attach. If the requested CAD
work requires starting SolidWorks and no instance exists, use
`start_if_missing=true`. Keep CAD and MCP under the same Windows user and integrity level.

Before modifying an existing model, inspect its exact title/path and configuration.
Activate the intended open document, then call `solidworks_bind_document` with its
exact `title` and `expected_path`. Pass the returned `document_token` to every
existing-document write, including dimension edits, save/export, metadata and
configuration changes. New/create/open tools return their own token. Rebinding
invalidates the old token. Duplicate open titles are refused instead of guessed.
The token binds the COM document object, path, title and configuration; a detected
switch stops the write. Human UI and unrelated automation do not share the MCP lock.

Prefer `solidworks_create_parametric_part` for block/cylinder/tube/flange/stepped_shaft.
For custom parts read the installed `schemas/feature-graph.schema.json`, the
`examples/cylinder-feature-graph.json`, and the relevant README section. Compile
with `solidworks_compile_feature_graph` before execution. Native graph dimensions
are mm/degrees; the backend converts them to metres/radians. Reject non-finite
numbers before sending them. A graph creates a new part; it is not an assembly API.

Choose a fresh output path per build. Save/export refuse existing files unless
`overwrite=true` is explicitly supplied as part of the user's save task. Explicit
overwrites retain a backup in `.swmcp-backups`. Rebuild, feature errors and solid
volume are checked before saving; block/cylinder/tube builds also check analytic
volume. These checks do not establish manufacturing compliance or recover hidden
dimensions from a photo. Reopening the result adds stronger disk evidence.
Use `solidworks_capture_view` for visual evidence when useful.

Use one unique `request_id` per logical operation. Exact successful retries replay
the durable result; changed parameters or document tokens with that ID conflict.
On timeout, query `solidworks_operation_result(request_id)` and
`solidworks_operation_status`: timeout does not cancel COM. FAILED/RUNNING/UNKNOWN
mutations are never automatically replayed. After an incremental failure, inspect
the model and visible Undo group. If partial changes have been inspected and
recovered or intentionally accepted, explicitly rebind with
`acknowledge_partial_changes=true` and use the new token. Never blindly undo the
user's last action. Runtime reload is disabled in code; restart the idle MCP to update.

Incremental edits do not save automatically; save explicitly when the task requires
a saved deliverable. A returned `ok` does not establish geometric correctness.
Distinguish protocol checks, mock tests, and live SolidWorks verification in reports.

`solidworks_create_two_stage_reducer` builds a multi-body `.sldprt`, not a constrained
`.sldasm`. `solidworks_create_output_shaft_from_dwg` builds a hard-coded example,
not a general DWG reader. Concept spur gears are not involute gears; even the
involute generator needs engineering validation before manufacturing use.

For version-specific revolve and save behavior read
`references/compatibility-and-lessons.md`.

## 通用规则与中文工作树

默认工作树使用中文。优先用“对象/用途＋操作＋关键参数”，如“安装孔定位基准面”“底座拉伸_10mm”。
图的 name 保留稳定内部ID，display_name 用中文；编译器同步转换引用并返回 name_map。
独立编辑应查询实际中文特征名/尺寸名，不将内部图ID当原生CAD句柄。
未提供显示名时，中文模式自动生成可读的操作名称；不允许重复显示名或与系统基准面重名。

复杂斜切、圆角/倒角交界、放样或自定义参考面建模前，读取[通用建模规范](references/modeling-guidelines.zh-CN.md)。
调用 solidworks_review_feature_graph 或查看编译/图纸验证结果的 planning_review。
离线复核只检查规划条件和风险，不能代替实际实体和局部交界的验证。

不要机械地规定圆角最后做，也不要把一次放样修复推广为所有切除的默认方法。
按设计轮廓、切点/交线、选边依赖和切除侧边界选择方法与顺序；检查近端/远端及必要中间截面。
参考面应明确坐标、法向、单位、关联方式和拉伸方向，不能反复微移来碰运气。
分层核对重建、尺寸/实体数/体积、局部拓扑和磁盘/中性文件；制造要求单列。

多实例与保存失败时，先区分目标PID/文档、几何、API绑定和临时目录。
TEMP/TMP的修正只对新进程生效，不假定已经运行的旧实例环境随之更新。
清理只在用户当前授权范围内执行，保留最终模型、参数与来源和关键证据；不强制处理占用文件。
部署更新前按通用规范检查配置编码和实际启动；Skill正文放在SKILL.md，TOML只保留配置项。
