@echo off
:: 以管理员身份运行此脚本，开放局域网访问所需端口
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 请右键本文件 → "以管理员身份运行"
    pause
    exit /b 1
)

echo 正在添加防火墙规则...

netsh advfirewall firewall delete rule name="FHD - Frontend Dev (5001)" >nul 2>&1
netsh advfirewall firewall delete rule name="FHD - Backend API (5000)" >nul 2>&1

netsh advfirewall firewall add rule ^
  name="FHD - Frontend Dev (5001)" ^
  dir=in protocol=TCP localport=5001 ^
  action=allow profile=any ^
  description="FHD Vite 前端开发服务器，局域网设备访问"
if %errorLevel% equ 0 (
    echo [OK] 端口 5001 入站规则已添加
) else (
    echo [FAIL] 端口 5001 规则添加失败
)

netsh advfirewall firewall add rule ^
  name="FHD - Backend API (5000)" ^
  dir=in protocol=TCP localport=5000 ^
  action=allow profile=any ^
  description="FHD FastAPI 后端，仅 Vite 代理使用，勿直接暴露公网"
if %errorLevel% equ 0 (
    echo [OK] 端口 5000 入站规则已添加
) else (
    echo [FAIL] 端口 5000 规则添加失败
)

echo.
echo ==============================
echo 完成！局域网其他设备现在可以访问：
echo   前端：http://192.168.3.137:5001
echo ==============================
echo.
pause
