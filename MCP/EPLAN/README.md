# EPLAN 2.9 native MCP and design review

独立的 Python stdio MCP → 本机命名管道 → EPLAN 进程内 C# Add-in。
源码来自本项目已运行的原型，并进行了路径、超时、文档与设计审查方面的改进。
配套 Skill：[eplan-native-design](../../skills/eplan-native-design/SKILL.md)。

## 可用范围

- 默认 `review`：读取明确指定的已打开工程/页面、原生元件/引脚/连接，提供工具目录、本机 build 核对、本地帮助检索、设计意图及完整快照检查。以实际工具目录为准。
- 可选 `trial`：保留历史电机案例工具；只允许专用实例、固定 `workspace/motor_forward_reverse_trial.elk`、已知 schema、编译哈希及对象前置条件。部分旧阶段工具在新修订中已退役，出现在目录不代表可以重放。
- 通用读取不是任意工程编辑；尚未实现通用厂家宏导入、全局部件库写入或任意新工程自动完整生成。
- 历史工程、原生身份快照、哈希计划、交付包与厂家资料属于私有输入，未随仓库发布。没有它们仍可启动只读服务、检索本机文档并验证新意图模型。
- 本次代码编译或离线测试不等同于新 DLL 已在 EPLAN 换载、工程回归、PLC 运行或施工放行。

## 安装与配置

在仓库根目录执行：

```powershell
python -m pip install -e ./MCP/EPLAN
```

这是独立服务，不通过 `AI_CAE_MCP_SOLVERS` 启用。使用 editable install，或从检出的
`MCP/EPLAN/server.py` 启动；Python 包也包含意图 schema。Add-in 源码留在检出目录。

复制 [配置模板](examples/config.example.json) 到被 Git 忽略的 `private/` 目录，
填写自己的绝对本地路径。模板中的尖括号值不能直接运行。

| 配置 | 含义 |
|---|---|
| `workspace` | 私有工作目录；历史案例数据在其 `artifacts/` 下 |
| `eplan_exe` | 用户安装的 EPLAN.exe；不扫描磁盘猜测安装位置 |
| `help_roots` | 本机 2.9 SDK XML、HTML/Markdown 帮助目录，最多 8 个 |
| `profile` | 默认 `review`，仅显式配置才使用 `trial` |
| `expected_build` | 当前编译/写入约束为 `2.9.4.14642`，改字符串不代表兼容新版本 |
| `timeout_seconds` | 单次管道 I/O 总截止时间，默认 65 秒 |

环境变量 `EPLAN_MCP_CONFIG` 指向私有 JSON；可用 `EPLAN_MCP_WORKSPACE`、
`EPLAN_EXE`、`EPLAN_MCP_PROFILE` 覆盖相应字段。配置在进程内固定，修改后重启 MCP。
没有配置时以只读模式启动，不会隐式启动 EPLAN 或打开项目。

Codex 注册模板：[examples/codex-config.example.toml](examples/codex-config.example.toml)。
填写安装本包的 Python 和私有配置文件绝对路径，加入个人 Codex 配置。

## 原生 Add-in

需要新工作站的实际绘图时，可另外配置 Canary 通用 MCP 与本项目
[工作站原生实施扩展](authoring/README.md)。该接口独立于本服务的 review/trial 范围；
已实现独立新工程的计划实施与回读，不修改历史试验工程的身份或限制。
它仍是限定工作站适配，不能据此宣称任意工程自动生成或厂家宏导入已完整支持。

```powershell
$env:EPLAN_EXE = '<your-installed-EPLAN.exe>'
powershell -File ./MCP/EPLAN/addin/build.ps1
```

编译器引用本机同版本 API 程序集，输出在忽略的 `MCP/EPLAN/private/addin/`，不提交 DLL。
注册使用 EPLAN 自身的 `EplApiModuleAction /register:<absolute-dll-path>`；首次安装或
升级前确认注册目标与专用实例，避免同时加载同一桥接的两份 DLL。编译不自动注册或终止 EPLAN。

需要历史试验操作时，用 `addin/launch-trial.ps1 -Workspace <private-workspace>` 启动
专用实例；脚本同时传入 `EPLAN_MCP_TRIAL_INSTANCE=1` 与 `EPLAN_MCP_WORKSPACE`。
两个进程必须指向同一私有工作目录。写操作前 Python 再做 hello 确切 build 核对。

新 Add-in 会取消排队但尚未执行的超时任务。任务已经进入原生 API 时不能安全回滚或强停，
返回结果未知并停止后续原生命令；Python 超时/断连也不自动重试写入。
Windows 命名管道总时限与同线程取消 I/O 有真实管道测试，但 GUI 队列超时分支仍需要
在专用 EPLAN 实例内验证，不能由管道测试替代。

## 使用顺序

1. `eplan_capabilities` / `eplan_tool_catalog`：确认真实能力与 profile。
2. `eplan_bridge_discover` / `eplan_bridge_health`：确认实例和 build。
3. `eplan_projects_list` / `eplan_pages_list` / `eplan_page_inventory`：只读回读显式工程。
4. 配置本机帮助目录后 `eplan_help_index`，再 `eplan_help_search` 精确查 API。
5. 对新设计使用 `eplan_design_intent_validate`，然后选择已实现的原生写入/审查流程。

`eplan_page_inventory` 在原生回复之后做客户端分页；大页仍受 4 MiB 原生帧限制。
返回一页不构成全工程验收。帮助索引使用 SQLite FTS5，SDK XML 按 member 独立索引；
不会解包 CHM、运行文档代码或上传手册。索引目标标为 2.9，并不自动检测源文档版本；
调用者仍须核对配置目录和资料版本，不能套用 2027 的签名。

资源：`eplan://capabilities` 与 `eplan://schemas/design-intent-1`。

## 两案例经验与完整快照审查

电机正反转与输送推料的通用经验、案例边界见
[Skill 经验索引](../../skills/eplan-native-design/references/two-project-lessons.md)。
不把某个案例的CPU、I/O用途、速度给定或连接数当成其它工程默认值。

新增离线`eplan_native_snapshot_validate`，契约资源为
`eplan://schemas/native-snapshot-plan-1`。接受完整捕获envelope与已审查计划，
核对页/功能/引脚、精确边集合、重复/未布置线、容量及PLC分组地址。
可通过`semantic_model`与`port_map`复用意图模型，比较网络分区与required端口覆盖。
内部连续性只允许同一声明端子的引脚；不把触点、线圈或负载内部短接。

```powershell
python ./MCP/EPLAN/scripts/review_native_snapshot.py --plan ./MCP/EPLAN/examples/native-snapshot-plan.json --capture ./MCP/EPLAN/examples/native-snapshot-capture.json
```

这些公开JSON是合成测试夹具，不是实际EPLAN输出。新审查工具永远声明
`native_read_this_call=false`，不采集新数据，不代替历史固定模型验收器，也不批准施工。
只比较精确边集而未提供语义模型时，会明确返回未检查电气意图。

工作站写入仍由独立[authoring扩展](authoring/README.md)提供，当前源码有16个有界入口。
增加配置预检、可选MVID加载核对、带SDK/编译器摘要的构建收据，以及锚定已审查路由的重开校验。
通用审查工具增加不意味着任意工程写权限扩大。完整契约说明见
[验证契约](../../skills/eplan-native-design/references/verification-contract.md)。

局部控制线网的公开合成示例：[examples/control-intent.json](examples/control-intent.json)。
它只演示 PLC 电源/公共端和两个继电器线圈，不含完整安全、动力或 VFD 接口，不能施工。

```powershell
python ./MCP/EPLAN/scripts/review_intent.py ./MCP/EPLAN/examples/control-intent.json
python -m pytest -q ./MCP/EPLAN/tests
```

意图审查覆盖端点/标识、线网连通、相线/N/PE 与直流电位冲突、端子接线容量、PLC
地址别名和公共端分组、明确声明的互锁/防重启/停稳要求。它不模拟触点、PLC 代码或功能安全；
`ok` 不等于原生工程通过、设备规格合理或施工放行。

合法的单点 0V/FE—PE 参考连接需要在 `intentional_bonds` 中以 `connection_id` 和
`reason` 明确声明。移除这些连接后必须恢复电位分离，并拒绝第二条并行参考路径；
N—PE/相线混接不能使用这个例外。这只校验意图拓扑，不批准现场接地方案。

## 研究与证据

- [GitHub 同类项目比较与本次验证](docs/eplan-mcp-comparison-2026-10-26.zh-CN.md)
- [两个项目的经验沉淀与本轮验证范围](docs/eplan-two-project-hardening-2026-10-30.zh-CN.md)
- [导入源码指纹](SOURCE_PROVENANCE.json)：改造前的项目自有源文件哈希，无本机作者路径。
- [官方 2.9 连接原则](https://www.eplan.help/en-us/Infoportal/Content/Plattform/2.9/Content/htm/connectionbrowsergui_k_prinzipverbindungen.htm)：图形自动连接在生成原生连接后才具备相应连接数据。

这里没有复制同类项目实现、厂家 DLL、商业手册、客户数据库或许可文件。社区项目是比较资料，
其文档中的许可推断与本机权限分别核实；本包不会通过反射绕过厂商许可。
