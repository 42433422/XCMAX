@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   MODstore 市场部署 / 重启
echo ========================================
echo.

echo [0/4] 释放端口 8765（若上次未正常退出）...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue ^| ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

echo [1/4] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)
echo [OK] Python 已安装

echo.
echo [2/4] 安装依赖...
python -m pip install -q -e ".[web,knowledge]"
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo [OK] 依赖安装完成

echo.
echo [3/4] 构建市场前端 ^(market\dist^)...
where npm >nul 2>&1
if errorlevel 1 (
    echo [提示] 未找到 npm，跳过构建。若页面空白请先安装 Node 并在 market 目录执行 npm install ^&^& npm run build
) else if not exist "market\package.json" (
    echo [提示] 未找到 market\package.json，跳过构建
) else (
    pushd market
    call npm run build
    if errorlevel 1 (
        echo [警告] npm run build 失败，请检查 market 目录；将尝试使用已有 dist
    ) else (
        echo [OK] 前端构建完成
    )
    popd
)

echo.
echo [3.5/4] 自检邮件服务...
for /f "delims=" %%i in ('python -c "from modstore_server.email_service import email_status; print(email_status()['mode'])"') do set EMAIL_MODE=%%i
if "%EMAIL_MODE%"=="smtp" (
    echo [OK] 邮件服务已配置 ^(SMTP^)
) else if "%EMAIL_MODE%"=="debug" (
    echo [提示] MODSTORE_EMAIL_DEBUG=1，验证码会打印到控制台而非真实发信
) else (
    echo [警告] 邮件服务未配置或仍是占位符（如 your-qq-smtp-auth-code / CHANGE_ME）
    echo   - 注册 / 找回密码 / 验证码登录会失败
    echo   解决方案三选一：
    echo     A. 编辑 .env 把 MODSTORE_SMTP_USER/MODSTORE_SMTP_PASSWORD 改为真实凭证
    echo     B. 临时调试：set MODSTORE_EMAIL_DEBUG=1 然后重启
    echo     C. 直接启动后用 POST /api/admin/email/test 验证 SMTP
)

echo.
echo [4/4] 启动服务 ^(Ctrl+C 停止；代码变更可再加参数 --reload^)...
echo.
echo 请访问: http://localhost:8765/market
echo 注册页: http://localhost:8765/market/register
echo API 文档: http://localhost:8765/docs
echo.

REM ---------- QQ 邮箱发「真实」验证码 ----------
REM 1）浏览器打开 https://mail.qq.com → 设置 → 账户 → 开启 POP3/SMTP → 生成「授权码」（不是 QQ 密码）
REM 2）去掉下面几行开头的 REM，把账号、授权码改成你的；不要设 MODSTORE_EMAIL_DEBUG（或设为空）
REM set MODSTORE_EMAIL_DEBUG=
REM set MODSTORE_SMTP_HOST=smtp.qq.com
REM set MODSTORE_SMTP_PORT=465
REM set MODSTORE_SMTP_USER=你的QQ号@qq.com
REM set MODSTORE_SMTP_PASSWORD=你的SMTP授权码
REM set MODSTORE_SENDER_EMAIL=你的QQ号@qq.com
REM set MODSTORE_SENDER_NAME=XC AGI

set MODSTORE_ADMIN_RECHARGE_TOKEN=your-secret-token-here
python -m uvicorn modstore_server.app:app --host 0.0.0.0 --port 8765 --reload
