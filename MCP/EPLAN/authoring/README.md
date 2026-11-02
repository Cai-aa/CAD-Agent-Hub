# EPLAN 2.9 工作站原生绘图扩展

此目录是本项目自有的、限定工作站计划的 typed API 适配器。通过
[Canary-ECAD/eplan-mcp](https://github.com/Canary-ECAD/eplan-mcp) 的本地扩展机制加载，
独立于历史电机试验 Add-in，不修改其固定工程、白名单或哈希限制。

历史原生验证build：EPLAN 2.9.4.14642。新代码的编译、离线测试和原生运行回归分别记录，不能互相替代。
不是任意版本/任意工程的通用生成器。
Canary 本身提供通用原理图探索、放置、接线和读回工具；此扩展提供第二套工作站计划的有界批量实施。

## 环境与安装

先安装 Canary MCP 的依赖并设置 `EPLAN_PLATFORM_ROOT`；此值来自本机私有配置。
默认使用 discovery 模式，通过 `eplan_tools_search/describe/call` 调用隐藏工具。
把 `EPLAN_MCP_EXTENSIONS` 指向本目录，运行 `build.ps1 -EplanBin <installed-bin>`。
DLL名绑定源码、SDK引用和编译器摘要。构建在独立临时目录完成后发布DLL；已有输出必须有摘要/MVID匹配的收据才复用，不覆盖未知文件。编译不会注册/卸载全局Add-in，也不会重载当前MCP进程。

私有配置需要这些绝对本地路径和摘要，不提供作者机器路径：

- `EPLAN_WORKSTATION_ROOT`：专用工程根目录。
- `EPLAN_WORKSTATION_PLAN` / `EPLAN_WORKSTATION_PLAN_SHA256`：已审查的原生计划。
- `EPLAN_WORKSTATION_DLL` / `EPLAN_WORKSTATION_DLL_SHA256`：本机编译结果。
- `EPLAN_WORKSTATION_DLL_MVID`：建议从构建收据填入；启用后在原生入口之前核对实际加载的程序集。
- `EPLAN_WORKSTATION_TIMEOUT_SECONDS`：传给上游脚本执行器的结果文件等待阈值，默认75秒，允许1至180秒；不是完整WCF调用或诊断的总时限。MCP客户端截止时间另行设置，超时不自动重试写操作。
- `EPLAN_WORKSTATION_FORMAT_SHA256`：可选的专用排版修订摘要。
- `EPLAN_WORKSTATION_REBIND_SHA256`：跨进程重新绑定时的历史原生基线摘要。

商业 API DLL、工程数据库、厂家手册、实际绘图计划、身份基线和编译结果不随公开源码分发。
没有匹配私有计划时拒绝执行。配置变化需要新 MCP 进程；更换磁盘源码不等于已加载代码更新。

配置模板：[环境JSON](environment.example.json)、[schema](environment.schema.json)、[独立Codex服务](codex-config.example.toml)。
模板占位值不能直接执行；环境JSON只包含此扩展字段，不是完整Canary配置。

```powershell
python ./MCP/EPLAN/scripts/authoring_preflight.py --environment <private-environment.json>
```

`eplan_ws_preflight`和独立CLI均不连接EPLAN。基础配置与各操作的辅助计划状态分别返回；
它不证明原生build、许可、连接或已加载DLL相容。MVID未配置时明确披露守卫未启用。
源文件与加载指纹不一致时要求新MCP进程，配置缺失/摘要变化在调用前拒绝，实际卷不可用时返回停止原生操作的诊断。

## 原生写入边界

仅接受 `eplan-workstation-native-1`、固定新工程名 `Conveyor_Pusher_R1` 和本机根目录。
首次 prepare 不覆盖已有 ELK/EDB；每页绑定 native object、symbol、page 和位置。
不开放调用者 C#、任意 Action 名或任意目标路径。16 个 typed 工具通过 `eplan_ws_` 前缀索引。
所有原生操作顺序执行，不并行访问一个 EPLAN 实例。

主要流程：prepare → catalog → apply_page → snapshot → normalize_connections →
format_drawing → check_project/export_pdf/backup_project。
repair_star_sources 是早期修订的专门修复；已排版修订不得重放旧附件排序。
重新打开工程后先 inspect_reopened_identity，完整核对后再 bind_verified_reopened_identity。
绑定只更新桥接元数据，不重画或修改原生工程。

重开时不仅核对state：还核对基线锚定的format/safety计划摘要、精确路由、
引脚方向/容量以及中断点位置、源标志和排序。篡改可变state不能成为通过重绑的依据。
EPLAN进程内同名旧程序集可能仍在使用，加载路径和已配置MVID守卫须在Execute之前通过。
端口连接和配置预检通过后仍可能没有原生回执。结果未知时停止后续原生命令，保留脚本与诊断，不能根据上游“未生成结果文件”推断一定没有执行。上游超时后可能另发只读诊断脚本；这不等于重放原始写命令。

## 本机验证得到的注意事项

- 2.9 设置中断点排序码会清除本点的星形源标志；源标志在最后设置，并在生成连接后读回。
- 分支源按真实 `Pin.MaxConnectionCount` 选择，不调高上限来消除错误。PLC 连接点仍保守按单根外线处理。
- 原生 pin 的逻辑默认编号不等于厂家印字；同时回读 `FUNC_CONNECTIONDESIGNATION`、PLC 地址和映射。
- 数据库编号是会话身份的一部分，不能跨进程直接复用。结合持久 GUID、稳定 type/object ID、
  全部功能/引脚/PLC 地址及 typed edge set 核实后才重新绑定。
- 原生 PDF 与图页数据同轮导出；直接对齐的引脚生成原生导线，跨页用 BPIN。
  绘图线不作电气连接替代；2D 布局矩形明确标为概念，不冒充厂家外形宏。
- backup 仅使用 MakeBackup，固定在专用根目录下生成新 ZW1，不暴露 SourceOut/Archive。

连接校验与所选 EPLAN 检查方案通过仍不批准施工、机器安全、保护整定或 PLC 投运。
公开适配器没有通用厂家宏导入或自动完成所有现场参数的能力。

## 安全专项修订

`safety_review_apply` 只实施独立审查并绑定摘要的 R1→R2 增量，使用私有
`EPLAN_WORKSTATION_SAFETY_SHA256` 与固定根目录中的 `workstation-safety-R2.json`。
完整检查功能、引脚、PLC 地址、全部连接、中断点和文字前像；开始后禁止自动重放，
并停用 R1 的 apply/format/normalize/repair/polish 修改命令。

`safety_review_annotations` 使用 `EPLAN_WORKSTATION_NOTES_SHA256` 和固定
`workstation-safety-notes.json`，只修改签定的文字、功能说明和触点映像位置。
后续文字修订必须链接前一完整修订摘要；部分失败时拒绝后续修订。
同版本 SDK 表明设置 ContactImage.RelativeLocation 会启用 AutoAlign，
故手动定位后必须最后设 AutoAlign=false，并核对导出。

两个工具均不下载 PLC、不写驱动参数、不表示整机安全认证。
单接触器、普通命令继电器、执行器电源恢复、续流释放延迟和气动复压均须单独复核；
新增冗余及反馈不能代替 PLr、故障排除、共因失效、接地及停止距离验证。
重新打开的身份基线必须同时包含当前 safety/notes 摘要及全部原生对象，
不得沿用较早的功能数量或给旧快照改摘要。

## 构建与回归

编译器TEMP/TMP临时改为当前OutputDir内目录，结束后恢复调用进程原值；不修复其它CAE任务或外接盘的全局设置。
`*.build.json`保留源码、SDK引用、编译器、DLL摘要、MVID与目标build。输入变化生成不同名称，缓存输出摘要或MVID变化则拒绝复用。

公开CI只跑离线/IPC测试，Windows使用合成CLR参考程序集测试构建、缓存与MVID拒绝，不含商业SDK或生产工程。
实际原生适配仍须本机同版本SDK编译及受限实例验证；Python测试通过不能声称所有新增原生路径均已实测。
