# NX MCP(路线 A)

用 Claude Code 通过 MCP 驱动**正在运行的 Siemens NX 2412** 进行三维建模。

## 为什么是路线 A

NX 2412 没有主线程 timer/idle 回调,也不带 PySide,所以 Abaqus MCP 那种"后台收包 → 主线程定时器泵 marshal 回主线程"的干净设计**无法复刻**。本项目改用:

- 一个 **daemon TCP server 线程**只做 socket 收发,不碰 NXOpen;
- 每个请求进队列,连接线程等 `Event`;
- **唯一一个常驻 worker 线程**串行 drain 队列,是**唯一**调用 NXOpen 的线程。

NXOpen 官方非线程安全、要求主线程调用。路线 A 故意从单一后台 worker 调它——这是整套设计的**承重假设**,必须用 `smoke_test.py` 验证。纯建模(特征/布尔/保存)通常没问题;碰 UI/显示刷新的调用可能不稳。

## 架构

```
Claude Code ──stdio──> mcp_server.py ──TCP(JSON/行)──> NX 内 nx_mcp_plugin.py
                                                          ├─ socket server 线程(仅 IO)
                                                          ├─ 请求队列
                                                          └─ 单 worker 线程 ──> NXOpen
```

## 文件

| 文件 | 跑在哪 | 作用 |
|------|--------|------|
| `nx_mcp_plugin.py` | NX 内(模块) | socket 桥 + 单 worker + NXOpen 操作 |
| `start_mcp.py` | NX 内(journal) | **import 并启动**桥(Start MCP 按钮) |
| `stop_mcp_nx.py` | NX 内(journal) | 停止桥(Stop MCP 按钮) |
| `mcp_server.py` | 你的 Python 环境 | stdio MCP server,TCP client |
| `stop_mcp.py` | 你的 Python 环境 | 外部 socket 发停止 |
| `smoke_test.py` | 你的 Python 环境 | **路线 A 验证**:ping + create_block |

## 第一次跑通(建议顺序)

### 1. 在 NX 里启动桥
1. 打开 NX 2412,**新建/打开一个模型零件**(必须有工作部件)。
2. 工具 → Journal → **播放(Play)**,选 `start_mcp.py`。
3. 信息/列表窗口应打印:`NX MCP bridge listening on 127.0.0.1:48160`。
4. NX 界面应保持可操作(不卡死)。

> 注意:必须播放 **`start_mcp.py`**,不要直接播放 `nx_mcp_plugin.py`——前者把桥作为模块导入,状态才能被 `stop_mcp_nx.py` 共享。

### 2. 验证路线 A(命门测试)
在你自己的 Python 里(stdlib 即可,无需装包):
```bash
python smoke_test.py
```
- NX 里出现一个 100×60×40 的长方体、返回 `ok: true` → **路线 A 在你机器上可行**。
- NX 崩溃/卡死 → 路线 A 不稳,需回退(见下)。

### 3. 接入 Claude Code
1. 装依赖:`pip install mcp`(在你的 Python 环境)。
2. 把 `examples/mcp_config.example.json` 的内容合并进 Claude Code 的 MCP 配置(改成你的 `python` 路径)。
3. 重启 Claude Code,应能看到 `nx` server 的 `ping` / `create_block` / `run_python` 工具。
4. 让 Claude:"ping 一下 NX",再"建一个 80×80×20 的长方体"。

### 4. 停止
- NX 内:播放 `stop_mcp_nx.py`(或 Stop MCP 按钮)。
- 外部:`python stop_mcp.py`。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `NX_MCP_HOST` | `127.0.0.1` | 监听地址 |
| `NX_MCP_PORT` | `48160` | 端口(避开 Abaqus 的 48152) |
| `NX_MCP_TIMEOUT` | `120` | 秒 |
| `NX_MCP_LOG` | `%TEMP%\nx_mcp_bridge.log` | 桥日志 |

## 路线 A 不稳时的回退

如果 smoke test 导致 NX 崩溃/不稳:
- 把 worker 限制为**只做纯建模**,绝不碰交互式 UI / 选择 / 显示刷新类 API。
- 退一步用**批处理模式**(`run_journal.exe` 每次冷启动执行一段)——慢但稳,无线程问题。
- 详见项目记忆 `nx-no-main-thread-timer`。

## 后续

- Start/Stop MCP 做成 Ribbon 按钮(MenuScript `.men` + `.tbr`,放 `UGII_USER_DIR`)。
- 扩工具:草图、拉伸、孔、阵列、布尔、导出 STEP 等(每个先在 NX 录 Journal 拿真实 API)。
