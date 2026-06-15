# 太阳鸟 PRO · Windows 定制安装包

修茈科技 · 基于 XCAGI v10 **企业版** 的太阳鸟客户专用安装程序（与通用 `XCAGI-Enterprise-Setup` **不是同一个包**）。

---

## 交付物

| 文件 | 说明 |
|------|------|
| `太阳鸟-Setup-10.0.0-x64.exe` | **定制安装包**（内嵌太阳鸟业务数据包，可选「获取数据」） |

通用企业客户仍使用 `release/xcagi-v10.0.0/enterprise/XCAGI-Enterprise-Setup-10.0.0-x64.exe`，**不含**太阳鸟数据。

---

## 客户安装

1. 双击 **`太阳鸟-Setup-10.0.0-x64.exe`**
2. 安装向导 → 勾选 **「获取太阳鸟业务数据（考勤模板与人员花名册）」**（默认已勾选）
3. 完成安装后启动 XCAGI，使用修茈企业账号登录
4. 直接进入 **考勤表转换**；模板位于 `%APPDATA%\XCAGI\424\`，人员已预置

勾选「获取数据」后自动写入：

- `424/考勤-2026-3月份考勤统计表.xlsx` — 固定考勤模板
- `data/mod_dbs/taiyangniao_pro.db` — Mod 侧库
- `config/sunbird-roster.json` — 人员花名册（首次启动写入主库）
- `mods/taiyangniao-pro`、`mods/attendance-industry` — 客户 Mod

---

## 供应商打包

### 方式 A：Mac 上用 GitHub Actions（推荐，等同云端 Windows 虚拟机）

先 push 本仓库（含 `sunbird-installer.yml`），然后：

```bash
bash FHD/scripts/package/stage-sunbird-delivery.sh --ci
```

会在 `windows-latest` 上编译，并自动下载 `太阳鸟-Setup-10.0.0-x64.exe` 到本目录。

### 方式 B：本机或虚拟机 Windows

```powershell
powershell -ExecutionPolicy Bypass -File FHD\scripts\package\build-sunbird-installer.ps1
```

### 方式 C：UTM / Parallels 虚拟机

在 Windows 虚拟机里克隆仓库，执行方式 B 即可。Mac 无法本地直编 `.exe`（NSIS + WPF 安装壳限制）。

种子数据 SSOT：`FHD/delivery/sunbird-seed/`

---

## 技术支持

- 版本：**10.0.0**
- 日志：`%APPDATA%\XCAGI\logs\`
