# CATIA 安全导出

`catia_export_active` 从 0.2.0 起不会直接把 CATIA `ExportData` 指向已经存在的正式文件。默认策略是拒绝覆盖，避免 CATIA 弹出模态确认框并阻塞整个 COM 工作线程。

## 接口

```text
catia_export_active(
    path,
    format_name=None,
    overwrite_policy="error",
    verify_reimport=True,
    request_id=None,
)
```

`overwrite_policy` 支持：

- `error`：默认值。正式目标已存在时立即返回错误，不调用 CATIA。
- `versioned`：正式目标已存在时生成带时间戳的新文件，例如
  `Engine_Turbine_Disk.__version_20260731_094400.step`。
- `replace`：显式替换。先导出和验证唯一临时文件，再通过文件系统替换正式目标。

## 固定执行顺序

1. 在进入 `ExportData` 前检查正式目标。
2. 为本次操作创建唯一临时文件，例如
   `Engine_Turbine_Disk.__exporting_20260731_094400_a1b2c3d4.step`。
3. 临时设置 `CATIA.Application.DisplayFileAlerts=False`。
4. CATIA 只向不存在的临时路径执行一次 `ExportData`。
5. 检查临时文件存在且大小大于零。
6. STEP/IGES 默认由 CATIA 重新打开，确认至少存在一个 Part Body/Shape 或 Product Component。
7. 关闭回读文档并恢复原活动文档。
8. `error`/`versioned` 使用文件系统重命名；`replace` 使用文件系统替换。
9. 无论成功或失败，均在 `finally` 中恢复 `DisplayFileAlerts` 并释放文档导出锁。

正式目标在CATIA导出和回读全部通过之前不会被修改。

## 超时和并发

- CATIA COM 仍由单一 STA 工作线程串行执行。
- 同一文档同时只能有一个导出任务。
- 工作线程忙时，新操作不会排队，而是返回“不要重试”的可恢复错误。
- 调用超时后先执行 `catia_operation_status`。只有 `retry_allowed=true` 才能考虑下一次操作。
- 超时后还必须检查正式目标和 `.__exporting_...` 临时文件，禁止直接重复导出。
- `request_id` 相同的已完成操作仍按原有幂等缓存返回。

## 示例

目标不存在时：

```json
{
  "path": "E:\\models\\Blade.step",
  "overwrite_policy": "error"
}
```

保留旧文件并创建新版本：

```json
{
  "path": "E:\\models\\Blade.step",
  "overwrite_policy": "versioned"
}
```

在完整验证后替换旧文件：

```json
{
  "path": "E:\\models\\Blade.step",
  "overwrite_policy": "replace",
  "verify_reimport": true
}
```

建模脚本不应在保存 `CATPart`/`CATProduct` 的同一函数末尾直接调用原始 `ExportData`。推荐把原生保存和交换格式导出拆成两个明确阶段，并统一通过该 MCP 工具导出。
