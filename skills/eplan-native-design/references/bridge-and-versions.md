# 桥接方式与版本

本仓库原生桥接采用 stdio MCP → 本机限长命名管道 → EPLAN 进程内 C# Add-in，GUI 线程串行访问 API，操作在 LockingStep 内完成。只把结构化操作与数据跨进程传递，不跨线程保存活的 EPLAN 对象。

2.9 包以本机安装目录的同版本厂商程序集编译；没有把 DLL 分发到仓库。`expected_build` 是写操作的显式兼容约束，修改它不会使未测试版本自动兼容。2.9 的 DataModelu 与新版本的程序集命名、.NET 运行时及 Remoting 设置分别核实，不能照搬 2026/2027 示例。

EPLAN 内置 C# 脚本、编译 Add-in、外部 Remote Client 属于不同执行环境。某个 namespace 在脚本编译器报 CS0234，不代表编译 Add-in 也不能用；反过来，外部脚本可运行也不证明当前 Add-in/许可证兼容。依据本机 XML、实际编译、hello 和原生回读，不把社区关于许可的推断当成厂商授权。

本包以 `review` 模式提供通用已打开工程的读取、本地帮助与离线意图检查；`trial` 保留原型的有限写入。其他 MCP 若提供宏、报表或典型回路复制，按其真实工具和版本边界使用，不能把宽泛执行入口自动算成可靠设计能力。

扩展一个原生写工具时，要同时给出结构化输入、目标身份、前置条件、有限变更、异常后的回读方案及可核对输出。先在可丢弃工程中编译/测试，再决定是否开放工具；不要先让模型生成任意脚本再把执行结果文件存在当作成功。

官方基准：[2.9 Generate API](https://www.eplan.help/en-us/infoportal/content/api/2.9/Eplan.EplApi.HEServicesu~Eplan.EplApi.HEServices.Generate.html)、[2.9 连接原则](https://www.eplan.help/en-us/Infoportal/Content/Plattform/2.9/Content/htm/connectionbrowsergui_k_prinzipverbindungen.htm)。

Canary的脚本timeout参数仅约束结果文件等待，远程调用及超时诊断可能另耗时；它不是本包命名管道总截止时间的同义词。端口连通、配置预检和原生回读分别报告。无回执时按结果未知停止，不推断脚本必定没有运行，也不自动重放。

Windows源码和stdio使用UTF-8，必要时用`python -X utf8`运行校验器。编译使用构建输出内的TEMP/TMP，不把其它CAE临时目录失效直接当作DLL源码错误，亦不自动修改全局环境或修复外接盘。
