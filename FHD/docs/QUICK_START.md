# XCAGI 快速开始

本指南说明企业桌面安装包的首次使用，以及研发人员如何在独立数据目录运行当前源码。产品版本、各平台可下载状态和安装包身份以 [发布目录](../config/download_release.json) 及对应原包清单为准，源码版本号不代表该版本已经发布。

## 客户：安装与首次使用

1. 从当前有效的交付入口取得适合本机系统与架构的安装包，核对对应清单的版本、构建 SHA 和 SHA-256。升级前按交付说明备份业务数据并退出旧程序。
2. 启动 XCAGI，使用自己的企业账号登录。安装包已包含运行环境，客户无需自行安装 Python 或 Node.js。
3. 首次设置依次填写**公司或团队名称**、选择或描述**行业**、确认**配置方案**，再进入工作空间。配置方案按账号权益及行业加载相应能力；首次设置不会自动写入演示业务数据。
4. 在设置中完成当前账号的模型配置，查看连接与执行器资格状态。连接测试通过后仍须等待所需运行资格完成；配置错误按页面提示处理。
5. 在智能对话或已授权的业务页面提交实际任务。涉及业务写入时，先核对识别结果和预演，再确认或审批。看到“已受理”表示任务进入执行流程，应继续查看原任务状态；结果待核对时，先检查原记录，避免重复提交。
6. 任务完成后下载结果，核对文件内容和业务记录，再进行后续工作。退出重开后确认公司、已授权能力及业务数据仍可读取。

数据目录与备份说明见 [本地数据策略](security/LOCAL_DATA_POLICY.md)；业务能力与完整交付清单见 [DELIVERABLE_PRODUCT.md](DELIVERABLE_PRODUCT.md)。

## 研发：运行源码

### 1. 安装依赖

后端使用 Python 3.11.5+，以 [pyproject.toml](../pyproject.toml) 为准。前端 Node.js 范围由 [frontend/package.json](../frontend/package.json) 的 `engines` 定义；当前支持 `^22.22.2 || ^24.15.0 || >=26.0.0`。同时开发前端与桌面壳时，需满足两者的依赖要求。

```bash
git clone https://github.com/42433422/XCMAX.git
cd XCMAX/FHD
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -c ops/deploy/requirements-server-api.lock.txt -r requirements-server-api.txt -e ".[server-api]"
```

Windows 可使用 `py -3.11 -m venv .venv` 创建环境，并在 PowerShell 中运行 `.venv\Scripts\Activate.ps1`。

此安装入口包含固定版本的 Agent SDK/CLI。实际模型任务还需要有效的模型配置与真实运行资格，见 [固定本地 Agent 执行器](../README.md#固定本地-agent-执行器)。

### 2. 构建前端

在 `FHD/` 下运行：

```bash
cd frontend
npm ci
npm run build:strict
cd ..
```

`build:strict` 先执行类型检查，再构建企业版前端，产物写入 `FHD/templates/vue-dist/`。当前 `npm run build` 与 `npm run build:full` 均构建企业版完整前端；两者不执行该类型检查，`build` 也不会自动切换为 generic 模式。

### 3. 启动独立的桌面模式后端

在 `FHD/` 下运行，将占位路径替换为**本次测试独用的绝对路径**：

```bash
python XCAGI/run.py --desktop --headless --host 127.0.0.1 --port 17500 --data-dir "<独立测试数据目录绝对路径>"
```

桌面模式在指定目录使用本地 SQLite，并在启动时完成迁移。浏览器打开 `http://127.0.0.1:17500/`，检查 `http://127.0.0.1:17500/api/desktop/status` 中的 `storageMode` 为 `local_sqlite`，然后按上面的首次使用流程登录。此方式启动后端和网页，不会创建 Electron 窗口。

现有 Windows 启动脚本 `start-desktop-sqlite.bat` 也可用于桌面开发。Web/PostgreSQL 部署另按部署配置迁移数据库，桌面与服务器运行差异见 [桌面平台一致性说明](desktop_platform_parity_ssot.md)。

### 4. 前端热更新

保留上一步后端进程，在另一个终端进入 `FHD/frontend/`：

```bash
VITE_API_BASE=http://127.0.0.1:17500 npm run dev
```

PowerShell 使用 `$env:VITE_API_BASE="http://127.0.0.1:17500"`，再运行 `npm run dev`。Vite 默认地址为 `http://127.0.0.1:42423/`，可通过 `VITE_DEV_PORT` 覆盖，以终端实际输出为准。`VITE_API_BASE` 应指向本次启动的后端端口。

## 研发：启动 Electron 窗口

先完成后端依赖安装及前端构建，再在 `FHD/desktop/` 执行：

```bash
npm ci
npm run build
PYTHON="<Python 3.11.5+ 解释器绝对路径>" \
XCAGI_PRODUCT_SKU=enterprise \
XCAGI_DESKTOP_USER_DATA_DIR="<独立测试数据目录绝对路径>" \
./node_modules/.bin/electron .
```

上述环境变量写法适用于 Bash。PowerShell 通过 `$env:变量名="值"` 设置后运行 `npx electron .`。Electron 会管理自己的后端进程，启动前先退出前一节手动启动的后端；不要让两个进程共用同一测试数据目录。

桌面壳默认后端端口为 `17500`，可通过 `XCAGI_DESKTOP_PORT` 覆盖。未显式指定数据目录时，macOS 默认位于 `~/Library/Application Support/XCAGI`，Windows 默认位于 `%APPDATA%\XCAGI`。前后端产品 SKU 应保持一致。

## 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| 前端或 Electron 依赖安装失败 | 先核对两个 `package.json` 的 Node.js 要求，再按锁文件执行 `npm ci`。 |
| 无法访问开发页面或 API | 核对实际启动端口和 `VITE_API_BASE`。本机代理可能影响回环请求，可用 `curl --noproxy '*' http://127.0.0.1:17500/api/health` 检查。 |
| Mod 页面缺失 | 检查账号权益、行业配置、Mod 加载状态和前后端 SKU；确认使用当前企业版构建。 |
| 模型连接成功但任务尚不可执行 | 查看执行器资格与原任务状态，处理实际错误后重新验证。连接测试不等于业务任务成功。 |
| 审批后仍在等待，或执行结果未知 | 回到原任务查看执行与核对状态；没有可靠完成回执时，不把等待显示为完成，也不重复创建同一业务操作。 |

## 交付验收

源码测试通过后，仍须在受保护主干完成集成，并从准确主干 SHA 构建原包。安装、升级、回滚和业务验收应记录同一原包身份；源码回归、模拟输入与客户实机验收的结果各按其实际范围登记。

客户原始 Excel 可用于识别和业务核对。程序读取、独立计算、客户人工核对以及 Excel/WPS 打开验证是不同证据，尚未执行的检查保持待验收。正式交付还需完成实际模型任务、目标设备运行及相应发布门禁。

完整清单见 [DELIVERABLE_PRODUCT.md](DELIVERABLE_PRODUCT.md)；版本和发布身份规则见 [PRODUCT_VERSION_SSOT](architecture/PRODUCT_VERSION_SSOT.md)。
