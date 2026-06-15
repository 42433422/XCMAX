# 太阳鸟 PRO · Windows 交付包

修茈科技 · XCAGI v10 企业版 + 太阳鸟考勤定制（`taiyangniao-pro`）

---

## 文件夹内容

| 文件 / 目录 | 说明 |
|-------------|------|
| `XCAGI-Enterprise-Setup-10.0.0-x64.exe` | **主交付物**：Windows 64 位安装程序（企业 SKU） |
| `数据/424/` | 可选：考勤固定模板（安装后复制到工作区，见下方） |
| `安装说明.txt` | 客户快速安装步骤 |
| `manifest.json` | 打包元数据（版本、SHA256、生成时间） |

> 安装包内**不含**太阳鸟定制 Mod；客户使用修茈市场账号登录后，由账号权益自动下发 `attendance-industry` + `taiyangniao-pro`。

---

## 客户安装（3 步）

1. 双击 **`XCAGI-Enterprise-Setup-10.0.0-x64.exe`**，按向导完成安装。
2. 首次启动 → 使用修茈市场分配的**企业账号**登录（生产认证：`https://xiu-ci.com`）。
3. 登录后进入太阳鸟界面：**考勤表转换**、**人员管理**、**部门管理**。

登录成功后浏览器/桌面壳地址示例：`/sunbird/#/taiyangniao-pro`

---

## 考勤模板（若本包含 `数据/424/`）

转换功能依赖固定模板，路径必须为：

```text
<工作区根>/424/考勤-2026-3月份考勤统计表.xlsx
```

**桌面版**：安装完成后，将 `数据/424/` 下全部文件复制到：

```text
%APPDATA%\XCAGI\424\
```

若该目录不存在，可先运行一次软件并完成登录，或在「考勤表转换」页面上传一次钉钉表后按提示创建工作区。

**首次使用建议**：在侧栏「人员管理」用「考勤统计表·明细导入人员」从模板导入花名册，再上传钉钉导出表转换。

---

## 供应商重新打包（Windows 开发机）

在 **XCMAX 仓库根目录** 打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File FHD\scripts\package\stage-sunbird-delivery.ps1
```

仅复制已有安装包、不重新编译：

```powershell
powershell -ExecutionPolicy Bypass -File FHD\scripts\package\stage-sunbird-delivery.ps1 -SkipBuild
```

产物输出到本目录 `太阳鸟/`。

---

## 技术支持

- 版本：**10.0.0**（v10 线内迭代，全产品线同锚点）
- 日志：`%APPDATA%\XCAGI\logs\`
- 可交付自检：安装后访问 `http://127.0.0.1:5000/api/platform-shell/deliverable-status`，`deliverable` 应为 `true`
