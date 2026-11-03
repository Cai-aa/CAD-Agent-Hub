# 从意图到原生证据

## 选择审查入口

尚未绘图时，用`eplan_design_intent_validate`检查`eplan-design-intent-1`。它检查声明的线网、公共端和约束，不连接EPLAN。正反转约束只在当前项目确实采用正反转时声明，不能给输送工作站凭空增加反转功能。

完整原生快照可用`eplan_native_snapshot_validate`或仓库`MCP/EPLAN/scripts/review_native_snapshot.py`，按`eplan://schemas/native-snapshot-plan-1`提供已审查计划和完整capture。它支持归一化的function/connection捕获格式，不直接接受旧电机collector摘要或单页分页结果。旧电机仍可使用其专有验收器。

此入口永远返回`native_read_this_call=false`。JSON中的source、success和哈希不证明它刚从EPLAN读取。需要新读时先获取本轮完整证据，再离线比较；不要从待检查快照本身生成相同预期计划制造通过。

## 原生契约内容

- 明确工程、build、全部页和功能，不依赖案例固定数量。
- `route_groups`第一个端点为源，三端组有两条预期边。完整集合比较之外，拒绝重复原生连接身份、重复边、自连、未知引脚及未布置线。
- 功能列出全部逻辑引脚，包括未用逻辑点；`displayed_designation`是脚号显示值，不用Pin.Designation默认编号替代。
- 校验原生容量及可选`external_wire_limit`，PLC连接点保守按一根外线。这不认证实际夹线孔或桥接配件。
- PLC通道声明`plc_device`、地址、变量；按PLC设备识别地址别名、DI/DO类型和脚号。盒子存在不证明公共端正确。
- `terminal_continuities`只能连接同一已声明terminal功能中的引脚，不能跨接器件、线圈、触点、电阻或VFD输入输出。

需要电气语义复核时同时提供`semantic_model`和`port_map`。语义模型复用design-intent schema，用映射端口比较两套网络分区，并检查required端口均已映射。端子内部连续性参与比较；接地参考仍按意图模型的显式单点例外检查，不把0V与PE/N混同。

没有语义模型时报告精确边集一致性，并保留`ELECTRICAL_INTENT_NOT_CHECKED`。缺少现场数据、元件定义、控制实现或安全验证时不能升级施工/投运结论。

## 复验和证据

公开capture是合成夹具，不能声称EPLAN执行成功。测试覆盖等数量但不同端点、对象ID错绑、地址别名、缺公共端和非法内部连续性，而不是只匹配输出文字。

保存输入哈希、采集时间、实例/build、完整消息及原生输出。通用扫描受文件分类和历史日志影响，结合原生契约解释等级，不改写旧报告或删除失败记录提高评分。
