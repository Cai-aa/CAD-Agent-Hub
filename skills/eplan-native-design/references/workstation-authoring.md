# 通用 MCP 与工作站原生实施

本机可以同时配置项目自有 `eplan29_lab`（review）、历史 `eplan29`（固定电机试验）和
Canary 上游的 `eplan_authoring`。使用前读取真实工具目录，不因一个服务只读就认定无法绘图。
Canary 的 discovery 模式通过 `eplan_tools_search`、`eplan_tools_describe`、`eplan_tools_call`
访问工具；版本显式选 2.9。本机路径由私有配置/环境变量提供，不使用社区默认安装目录。

`eplan_ws_` 是本项目独立的 typed 工作站计划扩展，不是对历史工程白名单的放宽。
仅在匹配的专用根目录、计划摘要、DLL摘要和 native build 下实施第二套工作站。
prepare 不覆盖已有工程，之后逐页 apply_page，保存身份与全部端点读回。
此实现仍不表示任意新项目均有现成批量编译器，通用工具与限定案例分别报告。

仓库有16个`eplan_ws_`入口，包括不连接EPLAN的`preflight`。先发现实际已加载目录，不把源码工具数量当作当前进程已更新。独立预检可运行`MCP/EPLAN/scripts/authoring_preflight.py`，各操作的辅助计划状态分别返回。

私有环境按`authoring/environment.schema.json`配置。构建收据含源码、编译器、SDK引用、DLL摘要与MVID，建议配置`EPLAN_WORKSTATION_DLL_MVID`。未配置时预检披露守卫未启用，不能宣称已核对加载的程序集。源码变化后用新MCP进程，原生调用再检查加载路径及已配置MVID。

## 已验证的 EPLAN 2.9 行为

- BPIN 排序码必须先设置，再把源点 `IsStarSource=true`，并在生成连接后读回；
  颠倒顺序会使星形源变成普通中断点，图形有线却缺少计划中的分支连接。
- 原生 `Pin.MaxConnectionCount` 参与分支源选择。线圈抑制模块和电机PE引脚可能只允许一条连接。
  不能调高该属性来消除错误；分支移到适当端子/线圈连接处。PLC 物理端子保守按单根外线处理，
  API逻辑容量不等于厂家压线容量。
- 同一PLC的主盒与辅助盒保留相同功能文本，页面上的中文说明可以不同，避免不同表达类型文本冲突。
- `Pin.Designation` 的默认逻辑编号不等于厂家脚号；同时核对 `FUNC_CONNECTIONDESIGNATION`、完整设备名、
  PLC地址与符号变量，不把默认“1/2”当成实际厂家端子。
- 只有两端同页、同轴且方向相对时才直接生成原生导线；跨页与多分支用中断点及明确端子链。
  对照完整 typed endpoint edge set 检查缺线、多线和未布置线。

## 重新打开后的身份处理

数据库编号包含会话身份，EPLAN重启后可能变化。写操作应先拒绝旧绑定。
随后用 `inspect_reopened_identity` 只读核对持久GUID、稳定type/object ID、全部功能/页/引脚/PLC地址
及全部原生连接；完全一致后才能 `bind_verified_reopened_identity` 更新桥接元数据。
不能直接修改保存的数据库编号来让检查通过。恢复过程中不重放未知结果的写操作。

重开校验将state路由绑定回哈希锚定的format/safety计划，比较中断点坐标、源标志、排序、引脚方向和容量。可变state不能单独成为重开通过的依据。

## 验收及交付

snapshot → 完整连接比对 → check_project → PDF视觉复核 → backup_project。
原生检查使用的方案名称和保留的Hint/Warning应随报告交付。
已声明备用且没有接线的端子可能产生“没有目标”警告，解释用途，不接虚假导线或关闭检查来追求0警告。

ZW1只使用MakeBackup，固定在专用目录生成新归档；不暴露SourceOut/Archive。
2D布局矩形只称空间方案，不能冒充厂家实物宏或加工图。
手工写入的选型表不等于原生厂家部件导入或报告引擎生成的采购BOM。

新安装的 `eplan-scripting` 可补充脚本/Remoting经验，但其对许可的笼统表述不是厂商授权保证。
以本机同版本SDK、实际编译、授权与回读为准；不上传私有工程到远程文档RAG。
