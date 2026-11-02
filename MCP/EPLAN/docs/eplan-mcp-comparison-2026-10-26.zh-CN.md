# EPLAN MCP / Skill 对比与改进记录

核实日期：2026-10-26。范围是公开 GitHub 源码、README、许可证和本机原型，
没有在同一台 EPLAN 上运行所有竞品，因此这不是速度、稳定性或绘图质量排行榜。
GitHub API 快照与修订见 [来源记录](eplan-github-sources-2026-10-26.json)。

## 独立判断

“GitHub 上有许多知名 EPLAN MCP/Skill”只部分成立。确实搜到多个项目，但结果中有
同一上游的 fork、旧名和镜像。此次较显著的上游是 Canary-ECAD/eplan-mcp，API 回读
为 129 Star / 30 fork；同组织独立 Skill 为 5 Star。其他对比候选多为 0–4 Star。
这些数字只是当日可见度，不能证明工程可靠性。

**通用功能覆盖，Canary-ECAD 当前更强。** 不能因为本机电机案例已经出图，
就宣称本项目全面超过它。它已有符号/路由目录、页面/器件写入、逻辑连接读取、
页面期望状态验证、scratch 工程和扩展入口。源码明确区分几何连接与逻辑连接，
所以也不能把它贬低成“只会画线”。

本项目原型的特色是一个真实 2.9 案例的 typed endpoint、计划哈希、数据库身份、
模型/采集器指纹与限定验收链。但这种可追溯性是针对该案例形成的，不能推导成
更高的泛化能力、全型号支持、生产可用或整体稳定性优势。

## 对比

| 方案 | 核实到的内容 | 更适合的方向 | 本次没有证明的部分 |
|---|---|---|---|
| [Canary-ECAD/eplan-mcp](https://github.com/Canary-ECAD/eplan-mcp) | README、catalog.py、schematic.py 和测试目录；有实际符号/引脚、布置、路由、逻辑连接读取和页面验证代码，目录支持 dry-run；多个新版本适配 | 广泛的交互自动化、通用探索和绘图开发 | 未在本机 2.9 运行，未与本项目作相同模型的现场或质量基准 |
| [Canary-ECAD/eplan-scripting-skill](https://github.com/Canary-ECAD/eplan-scripting-skill) | Skill 与逐层参考文档；区分脚本、API 与 Remote Client，涉及 2022–2027 版本差异 | C# 开发知识面、版本陷阱和 API 查询 | 社区对反射可达性/许可的说法不是厂商许可保证；没有因此修改本机许可边界 |
| [paulinholt/eplan-mcp-bridge](https://github.com/paulinholt/eplan-mcp-bridge) | README 与 EplanBridge.cs；编译的 typed DataModel DLL，包含页面/器件读写、复制、重命名与 typical 复用，使用 LockingStep | 从既有典型回路复用和批量调整 | 未进行本机 2.9 或完整接线的执行验证；复制 PLC 地址仍需工程决策 |
| [swater-kankyo/eplan-mcp-oss](https://github.com/swater-kankyo/eplan-mcp-oss) | README 与 ReferenceAddIn.cs；配置/协议清晰；参考 Add-in 的 switch 仅处理 ping 和 list_pages | 轻量桥接框架与扩展起点 | 上层工具包装不能证明原生插入、导出、删除等操作已完整实现 |
| 本项目改进前原型 | Python + typed C# Add-in、GUI 串行、固定案例计划和原生证据；源码有本机路径及累积历史入口 | 固定 2.9 电机案例的深度迭代与复核 | 通用工程写入、厂家宏、跨版本与其他模型均不能靠该案例推定 |
| 本次改进版 | 可移植配置、默认只读工具集、目录/能力资源、文档 FTS5、通用意图检查、管道截止时间与队列取消代码 | 保留案例原生能力，同时改善复用、查资料和设计前检查 | 通用意图检查还不是通用原生 apply；新 DLL 未换载时不具备新队列行为 |

另记录 [binfen1/Eplan_2026_IA_MCP_scripts](https://github.com/binfen1/Eplan_2026_IA_MCP_scripts)
与 [bingyongcao/eplan-api-skills](https://github.com/bingyongcao/eplan-api-skills) 的仓库元数据，
作为后续候选；本次没有深入核查其完整实现，不据此排名。

## 已落实的改进

1. **公开源码与私有数据分开。** 本机路径由私有 JSON/环境变量提供；客户工程、
   `.edb/.elk/.zw1`、厂家 DLL、手册、实际数据库身份及交付包不进入公共目录。
   [SOURCE_PROVENANCE.json](../SOURCE_PROVENANCE.json) 记录改造前项目自有源码指纹。
2. **能力发现与默认范围。** `review` 默认 14 个工具；通用已打开工程读取与固定试验
   写入分开。工具目录和能力资源报告实现边界，不用工具总数代替有效能力。
3. **桥接可靠性。** 限长帧、严格管道名、实际进程身份校验继续保留；加入总 I/O
   截止时间、同线程取消及严格回复封装验证。写入前核对确切 build。超时或断连不
   自动重试写操作，标记结果未知；新 C# 代码取消尚未开始的 GUI 排队任务。
4. **资料查询。** 从用户配置的本机 2.9 SDK XML/HTML/文本构建私有 FTS5 索引，
   SDK 以 API member 为独立记录；查询返回来源、哈希、变更状态。重建失败保留旧
   索引，源变动可识别。没有上传商业资料，也没有依赖第三方公开 RAG 的可用性。
5. **通用设计意图审查。** 独立 schema 检查未知/重复端点、导体电位的传递冲突、
   必需和禁止路径、容量、PLC 地址别名、I/O 公共端分组及明确的正反转约束。
   不把 PNP/NPN 当成所有公共端定义，不把规则通过当成 PLC 或安全功能运行成功。
6. **Skill 重构。** 移除本机路径与历史阶段堆叠，按桥接、设计、原生修改及案例边界
   分层。加强 PLC 盒子、实体脚号、中文注释、供电、电气连接、布局和交付的判断。
   保留实际授权范围与恢复规则，不增加重复确认流程。

实现入口：[MCP](../README.md)、[Skill](../../../skills/eplan-native-design/SKILL.md)。
原有已封存工程与原运行环境没有因迁移而重写；新代码会把与旧采集器绑定的快照判为
过期，需要新的原生采集，不会伪造更新旧报告哈希。

## 验证与实际限制

- EPLAN 扩展测试 **42 项通过**，包括反例、真实 Windows 命名管道、延迟/取消及 MCP
  SDK 的 stdio 握手，分别检查 review/trial 工具目录；这 42 项不是现场电气测试。
- 共享工具箱相关回归 25 项通过，Skill 结构验证通过；Python wheel 构建并检查 schema
  打包，来源/私有文件排除和相对链接检查通过。
- 已在实际注册的 `eplan29_lab` 配置下完成 SDK 握手，并从用户本机 2.9 资料建立
  32,699 条本地检索记录；Generate.Connections / LockingStep 查询及源文件哈希回查通过。
  这表示检索可用，不表示 API 已在某个新工程中执行。
- C# 全部源文件引用用户本机 EPLAN 2.9 程序集编译通过，输出 DLL 留在忽略的私有目录。
- Windows 实测发现并修正了 SQLite 连接未显式关闭导致索引替换失败，以及当前
  pywin32 的取消 API 差异。这是本次测试支持的修正，不是对厂商兼容性的推断。
- 未把新 C# GUI 排队超时分支在真实 EPLAN 内强制触发，未回放历史所有写操作，
  也未开展实机、FAT/SAT 或施工放行。历史案例的 139 项记录不冒充本次回归结果。
- 当前公共示例仅为独立编写的局部控制线网，含未选型项；不提供完整施工模板。

本次原始测试 XML、构建输出和本机配置放在被 Git 忽略的 run/private 目录，公开文档
只报告验证范围。仓库其他原有未提交改动予以保留。

## 下一步的优先级与成本

最值得继续的是为典型回路复用/宏插入建立可读的 dry-run 计划，绑定源模板、型号、
实体脚号及目标工程身份，然后逐类增加原生 apply/reconcile 与反例测试。这里需要
已验证模板、厂家数据与本机 API/许可测试，不能用扩大任意脚本执行入口代替。

通用宏/部件导入、原生报表与制造级布局需要更多厂家数据、许可和维护投入；多版本
Remoting/.NET 支持还要有对应版本的真实测试环境。远程知识服务可以增加检索覆盖，
也会引入资料外发、版本混用、服务可用性和运行费用，需要独立选择，未自动接入。

绘图质量最终应在同一输入、版本、部件与检查方案下比较：缺/多线、端点一致性、
PLC 分组、文字重叠、报表一致性、重开持久性和异常恢复。单个成功演示或 Star 差距
都不能替代这个基准。

## 官方语义基准

[EPLAN 2.9 连接原则](https://www.eplan.help/en-us/Infoportal/Content/Plattform/2.9/Content/htm/connectionbrowsergui_k_prinzipverbindungen.htm)
区分图形自动连接与生成后的连接；
[Generate API](https://www.eplan.help/en-us/infoportal/content/api/2.9/Eplan.EplApi.HEServicesu~Eplan.EplApi.HEServices.Generate.html)
提供连接更新服务。对本机编译 Add-in 和其他脚本环境的适用性分别核实。

本次未复制同类项目源码。后续若采用 MIT/Apache 实现，应保留各自要求的许可与版权
信息；不能因为本仓库是 MIT，就省略第三方的许可证条件。
