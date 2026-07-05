# XCMAX 桌面端备份与恢复

> 客户安装后，本目录的脚本由 NSIS 安装器自动注册为 Windows 计划任务。
> 运维人员也可手动执行本目录的脚本进行备份/恢复。

## 备份策略（双保险）

| 机制 | 触发时机 | 保留策略 | 说明 |
|------|---------|---------|------|
| **应用内调度器** | XCAGI 运行时，每 24h 自动备份 | daily 7 天 + weekly 28 天 | FastAPI lifespan 启动后台线程 |
| **Windows 计划任务** | 每日 12:30 + 每周日 12:30 | daily 7 天 + weekly 28 天 | 应用未运行时的补充备份 |

两者文件名格式一致，清理策略一致，互不冲突。

## 文件说明

| 文件 | 用途 |
|------|------|
| `XcagiBackup.ps1` | 备份脚本（调用 `xcagi-backend.exe --backup`） |
| `Install-BackupTask.ps1` | 注册 Windows 计划任务（安装时自动调用） |
| `Uninstall-BackupTask.ps1` | 卸载计划任务（卸载 XCAGI 时自动调用） |
| `XcagiRestore.ps1` | 手动恢复脚本（交互式选择备份） |

## 备份文件位置

- **本地**：`%APPDATA%\XCAGI\backups\xcagi-{version}-{stamp}.db`
- **外部（可选）**：通过 `-ExternalDir` 参数指定（如 USB 盘 `E:\XCAGI-Backup`）
- **日志**：`%APPDATA%\XCAGI\logs\backup.log`

## 手动操作

### 触发一次备份

```powershell
# 仅本地备份
powershell -ExecutionPolicy Bypass -File XcagiBackup.ps1

# 同时备份到 USB 盘
powershell -ExecutionPolicy Bypass -File XcagiBackup.ps1 -ExternalDir "E:\XCAGI-Backup"
```

### 恢复数据库

```powershell
# 交互式（列出可用备份，选择一个恢复）
powershell -ExecutionPolicy Bypass -File XcagiRestore.ps1

# 指定备份文件
powershell -ExecutionPolicy Bypass -File XcagiRestore.ps1 -BackupFile "xcagi-10.0.0-20260705123000.db"
```

恢复前会自动创建 `xcagi.db.pre-restore-{stamp}` 快照，便于撤销。

### 重新注册计划任务

```powershell
# 默认注册（无外部目录）
powershell -ExecutionPolicy Bypass -File Install-BackupTask.ps1

# 注册并配置外部备份目录
powershell -ExecutionPolicy Bypass -File Install-BackupTask.ps1 -ExternalDir "E:\XCAGI-Backup"
```

### 手动触发计划任务

```powershell
Start-ScheduledTask -TaskName XcagiDailyBackup
```

## 灾备硬约束达成

| 硬约束 | 达成方式 |
|--------|---------|
| 使用 `sqlite3.backup()` 在线热备份 | `xcagi-backend.exe --backup` 内部调用 |
| 备份后 `integrity_check` 校验 | `backup_database()` 已实现 |
| 每日 12:30 备份，7 天保留 | 计划任务 + 应用内调度器 |
| 每周日备份，4 周保留 | weekly 文件名标记 + 28 天清理 |
| 本地 + 外部双存储 | `-ExternalDir` 参数 + `XCAGI_EXTERNAL_BACKUP_DIR` 环境变量 |
| 恢复前创建快照 | `XcagiRestore.ps1` 自动创建 pre-restore snapshot |

## 故障排查

- **备份失败**：查看 `%APPDATA%\XCAGI\logs\backup.log`
- **计划任务未运行**：`Get-ScheduledTask -TaskName Xcagi*` 检查状态
- **数据库损坏自愈**：启动时 `recover_if_corrupt()` 自动从备份恢复（无需人工干预）
