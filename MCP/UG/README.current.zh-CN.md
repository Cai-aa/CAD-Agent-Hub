# Siemens NX MCP（当前修复版）

此版本通过 MCP stdio 服务连接 NX 2412 内的非阻塞 .NET Remoting 桥。`start_bridge.py` 只加载 DLL 后立即返回，不会让 NX 长期停留在“工作进行中”。旧的 Python TCP Journal 桥仅作为 legacy 参考。

## 已实现

- 会话与回读：`ping`、`get_part_summary`、`inspect_work_part_geometry`、`inspect_body_topology`、`resolve_topology`、`inspect_feature`、`rebuild_work_part`、`save_work_part`。拓扑回读包含稳定 ID 和几何回退条件，不再需要持久保存 NX 面/边列表下标。
- 零件与参数：`create_part`、`create_block`、`set_feature_expression`。
- 原生草图：`create_parametric_sketch`、`inspect_sketch`，支持线、矩形、圆、圆弧、几何约束和驱动尺寸。
- 通用特征：`extrude_sketch`、`revolve_sketch`、`sweep_sketch`、`loft_sketches`（实体或片体）。
- 细节特征：`create_cylindrical_hole`、`boolean_bodies`、`linear_pattern_feature`、`mirror_feature`、`fillet_edges`、`chamfer_edges`、`shell_body`。
- 数据交换：`export_exchange`、`import_exchange`，支持受限工作区内 STEP AP203/AP214/AP242 和 Parasolid `.x_t`/`.x_b`。
- 装配：`add_component`、`move_component`、`add_assembly_constraint`、`inspect_assembly`、`inspect_assembly_constraints`；固定、接触、配合、同心、距离、平行、垂直、角度和锁定对齐约束均可持久化并回读求解状态。
- 曲面：`extract_face_surface`、`offset_surface`、`trim_sheet_body`、`sew_sheet_bodies`，支持索引拓扑输入与结果体回读。
- 钣金：`create_sheet_metal_tab`、`create_sheet_metal_flange`、`create_sheet_metal_bend`、`create_flat_pattern`、`export_flat_pattern_dxf`；独立折弯工具使用稳定目标面选择器和折弯线草图。
- 工程图：`create_drawing_sheet`、`create_projected_view`、`create_drafting_note`、`create_drawing_linear_dimension`、`inspect_drawing_annotations`。线性尺寸与稳定选中的模型边保持关联，并回读实际测量值。
- CAM 基础：`get_cam_capabilities`、`initialize_cam_setup`、`create_cam_milling_context`、`inspect_cam_setup`、`define_cam_mcs`、`define_cam_workpiece`、`create_cam_mill_tool`、`create_cam_operation`、`set_cam_operation_geometry`、`configure_cam_milling_operation`、`generate_cam_toolpath`、`inspect_cam_operations`、`inspect_cam_operation_details` 和工作区内的 `export_cam_clsf`。铣削上下文会创建真正的非模板程序组、方法、MCS 与工件；面铣和型腔铣支持稳定几何、显式毛坯体、转速和进给。0.20 新增夹具/检查体分配，以及刀具、刀杆和多段刀柄参数。工序子类型先从当前 NX 实时枚举并校验，不假设旧版本模板名仍然可用。
- 机床构建与仿真：0.19 通过 NX 官方 Classic BC 模板构建运动学，绑定 OEM 分组几何，并把 25 个模板 Junction 全部重定向到 OEM 绝对坐标。NX 2412 实机回读已证明 X/Y/Z/S/B/C、31 个组件、25 个 Junction、`TNC_640` 通道和 `Z-Y-X-B-C` 五轴链。`export_machine_kit_from_reference` 使用 NX 官方导出的参考机床包作为合法容器，替换为已保存的 OEM 机床模型并脱敏，从而绕过 NX 2412 `MachineKitBuilder` 后处理阶段的内部错误 580055。若 NX 拒绝重复导出参考包，覆盖模式只允许复用已经完整性校验且脱敏的官方容器。`import_machine_kit_readback` 只在临时影子机床库中导入，验证全局机床数据库未变，再以非显示方式打开导入零件回读运动学；传入 `source_profile` 后还可按 OEM 碰撞矩阵执行不移动轴、不启动仿真的初始位姿静态间隙分析。
- 0.20 打通 CAM 与机床仿真上下文。`bind_isolated_machine_kit_to_cam` 把生成的 MTK 导入工作区持久化影子库，重复执行 NX 回读和静态碰撞验证，再挂载到当前 CAM Setup，全程不改全局机床数据库。`inspect_machine_simulation_readiness` 现在会检查 X/Y/Z/B/C 限位、有效刀轨、参数化刀具/刀杆/刀柄、零件、毛坯和可选夹具。受保护仿真由 NX AppDomain 内的 .NET 运行时持有控制面板，因此 `start_machine_simulation_with_collision_stop`、`inspect_active_machine_simulation` 与 `stop_active_machine_simulation` 三个独立 MCP 调用可以共享同一个真实 NX 面板。机床碰撞、轴限位、刀柄、刀具/零件、刀具/IPW、快速穿过 IPW 停止和精细材料去除均被强制开启。
- 0.20.1 在重定向 Junction 前把 OEM 机床参考位置解析为 Classic BC 模板的机床零点坐标。MTK 导出可在保留已分类库标识的同时指定唯一 `graphics_file_name`，避免 NX 已加载零件同名缓存重新打开旧机床几何。相同 libref 的 `reload_existing` 会先完成隔离导入与静态碰撞验证，再卸载当前机床；`restore_machine_build_recovery_part` 可在机床构建后安全返回原 CAM 零件。
- 受控 NC 输出：`postprocess_cam_program_locked` 默认禁用，只有设置 `NX_MCP_ENABLE_POSTPROCESS=1` 并提交精确的安全确认字符串后才会执行；输出仍标记为未生产认证，必须另做机床仿真、空运行和操作者批准。
- 专用与兜底：`create_involute_gear`；在显式启用时使用 `run_python` 补齐尚无专用工具的 NXOpen 操作。
- 响应大小限制、请求 ID 校验、仅本机 Remoting 端点，以及离线/真实 stdio 工具发现测试。

## 安装与 Codex 注册

在 PowerShell 中运行：

```powershell
Set-Location "C:\path\to\CAD-Agent-Hub\MCP\UG"
.\install_codex.ps1
```

脚本会创建项目内 `.venv`、安装 `requirements.txt` 中固定的 SDK、编译非阻塞 Remoting DLL/客户端，并注册名为 `siemens-nx` 的 stdio MCP。若同名服务已存在，脚本会停止，不会覆盖已有配置。

## 启动 NX 桥

推荐一次性安装自动启动：

```powershell
.\install_nx_autostart.ps1
```

该脚本把桥 DLL 部署到本项目的 `nx_user\startup`，仅在当前用户尚未配置其他 `UGII_USER_DIR` 时设置该环境变量。关闭所有 NX 会话并重新启动后，NX 会自动调用 DLL 的 `Startup()`，以后无需播放 Journal。可用 `uninstall_nx_autostart.ps1` 安全撤销环境变量；脚本不会删除文件。

手动备用方式：

1. 启动 NX 2412，并新建或打开一个 `.prt` 工作部件。
2. 选择“工具 → Journal → 播放”（快捷键 `Alt+F8`），打开 `start_bridge.py`。Journal 应在很短时间内结束；如果持续显示“工作进行中”，立即停止，不能继续使用旧的阻塞桥。
3. “工作进行中”应很快消失。服务日志位于 `%TEMP%\nx_mcp_remoting_server.log`，端点为 `http://127.0.0.1:48161/NXOpenSession`。
4. 在外部 PowerShell 运行只读诊断：

```powershell
.\.venv\Scripts\python.exe .\diagnose.py
.\.venv\Scripts\python.exe .\smoke.py
```

需要验证建模时再显式运行：

```powershell
.\.venv\Scripts\python.exe .\smoke.py --create-block
```

停止桥：关闭 NX，或使用“文件 → 实用工具 → 卸载共享映像”显式卸载 `NXMcPRemotingServer.dll`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe .\stdio_smoke.py
.\.venv\Scripts\python.exe .\stdio_live_e2e.py
```

需要创建受限工作区中的端到端测试部件时：

```powershell
.\.venv\Scripts\python.exe .\stdio_live_e2e.py --mutate
```

创建并验证默认的模数 2、20 齿、20° 压力角渐开线齿轮：

```powershell
.\.venv\Scripts\python.exe .\stdio_live_e2e.py --create-gear involute_gear_m2_z20_pa20.prt
```

原生草图、约束、尺寸与拉伸的实机端到端验证：

```powershell
.\.venv\Scripts\python.exe .\stdio_modeling_stage1.py
```

更多实机脚本：`stdio_modeling_stage2.py`、`stdio_modeling_stage3.py`、`stdio_exchange_stage5.py`。

## 安全与限制

- 默认只监听 `127.0.0.1`，不要把 Remoting 端口暴露到局域网或公网。
- `run_python` 能执行任意 NXOpen Python。若只需要专用工具，将 Codex 环境变量 `NX_MCP_ALLOW_EXECUTE` 改为 `0`。
- 内置 MILL E 500 U 机床配置只包含公开行程、回转轴范围和控制器系列，不包含厂家备份、序列号/许可证、私有路径、PLC/网络配置或专有后处理文件。
- 只有回读 `validation_passed=true` 且每个工序均为 `path_exists=true`，才能视为刀路生成成功；仅创建 CAM 工序或 Builder 校验通过不等于已有可用刀路。
- NX 2412 在非阻塞 Remoting 回调中可能让高层刀路生成器空返回。`generate_cam_toolpath(backend="auto")` 会逐项检查路径，仅对仍无路径的工序调用有 CAM 许可证要求的官方 `UF_PARAM_generate`，并在结果中明确返回 `fallback_used` 和每道工序采用的后端。
- 工序模板自带的默认对象可能仍是模板父级。应先调用 `create_cam_milling_context` 并使用其返回名称；`create_cam_operation` 默认拒绝模板父级，避免 NX 静默跳过工序。
- CLSF 是中性刀位文件，不是可直接上机的 NC 程序。机床运动学与生产后处理器未独立认证前，应保持后处理锁定。
- 机床库绑定推荐先运行 `inspect_machine_simulation_readiness(machine_query="...", required_axes=["X","Y","Z","B","C"])`，再调用 `bind_machine_tool_from_library(..., dry_run=true)`；只有预检返回有效后才把 `dry_run` 改为 `false`。替换现有机床还要求 `replace_existing=true` 和精确确认字符串 `REPLACE_EXISTING_MACHINE_TOOL`。绑定不会自动保存部件。
- 外部机床资料必须通过 `config/machine_sources.local` 配置为别名；该本地文件被 Git 忽略，MCP 只接受别名并对返回结果中的路径脱敏。可从 `config/machine_sources.example.json` 复制结构。先运行 `inspect_machine_source_profile`；若源 `.prt` 没有运动学，再运行 `inspect_machine_kinematic_plan` 检查轴链、限位和分组几何。构建计划通过不代表已成为 NX Machine Kit，也不代表生产认证。
- 机床构建保持源文件只读，产物限定在 MCP 工作区，默认 `dry_run=true` 并使用精确确认：Junction 重定向为 `RETARGET_MACHINE_JUNCTIONS`，完整 MTK 导出为 `EXPORT_MACHINE_KIT`，隔离导入为 `IMPORT_MACHINE_KIT_ISOLATED`，影子库 CAM 挂载为 `BIND_ISOLATED_MACHINE_KIT_TO_CAM`。0.19 继续拒绝只有 `kit_information.xml` 的空包，导出时移除私有元数据，而且不会把生成条目登记到用户的 Installed Machine。静态检查直接解析 OEM 声明的碰撞对与间隙，不使用通用猜测矩阵；若发现真实干涉，会返回对象包围盒、干涉点、方向和穿透深度。当前隔离导入的 MTK 已按 OEM 两组碰撞对及 2.5 mm 间隙完成回读，硬干涉、软干涉和接触均为 0。0.20 还要求 CAM 刀具与工件上下文通过后才能启动受保护仿真。以上结果均不是生产认证，NC 输出仍需独立校验、空运行和操作者批准。
- 外部模板中的 `.mch` 与分组 `.stl` 可用于建立 NX 组件树和 X/Y/Z/B/C 轴链；`.ctl/.ini/.vcproject/.VcTemplate` 属于第三方控制器/仿真资产，`.tcl/.def/.pce/.psc/.pui/.tbc` 属于后处理栈。后两类只作为工程参考，不会被嵌入仓库，也不会自动注册、启用或宣称适用于生产。
- `start_machine_simulation_with_collision_stop` 是刀轨驱动验证，不等于 TNC 640 控制器驱动的 NC 代码验证；真实 NC 代码仿真仍需匹配且经验证的后处理器、CSE/控制器模型、装夹与刀具组件。
- Remoting DLL 保持到 NX 关闭或通过“卸载共享映像”显式卸载；Journal 本身不会保持占用。
- 自动启动使用 NX 官方的 `%UGII_USER_DIR%\startup` 发现机制；若已有其他 `UGII_USER_DIR`，安装脚本会拒绝覆盖，应改用 `UGII_CUSTOM_DIRECTORY_FILE` 合并多套定制目录。
- stdio/协议/假 NXOpen 已自动验证；只有在真实 NX 中完成 `ping → part summary → create block` 后，才能宣称桌面建模链路完全通过。
- 当前专用工具已覆盖上述验证过的核心，但还不是“NX 全命令覆盖”。非平面曲面修剪和更多工程图标注类型仍是后续模块。应优先使用稳定 ID 或几何选择条件（法向、所在平面点、方向、长度、邻近点和确定性排序），避免持久化面/边下标；若上游建模确实改变了几何，应重新调用 `inspect_body_topology` 获取稳定引用。
