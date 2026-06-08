@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   MODstore Git 推送 + 构建
echo ========================================
echo.

REM 检查 git
where git >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Git，请先安装
    pause
    exit /b 1
)

REM 初始化仓库（如果没有）
if not exist ".git" (
    echo [1/5] 初始化 Git 仓库...
    git init
    git branch -M main
    echo [OK] 已初始化
) else (
    echo [1/5] Git 仓库已存在
)

REM 检查远程仓库
echo.
echo [2/5] 检查远程仓库...
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [提示] 未配置远程仓库
    set /p REMOTE_URL="请输入远程仓库地址: "
    if "!REMOTE_URL!"=="" (
        echo [错误] 地址不能为空
        pause
        exit /b 1
    )
    git remote add origin !REMOTE_URL!
)
git remote -v

REM 构建前端
echo.
echo [3/5] 构建前端...
cd market
if not exist "node_modules" (
    echo [提示] 安装 npm 依赖...
    call npm install
)
call npm run build
if errorlevel 1 (
    echo [警告] 构建失败，继续推送源代码
) else (
    echo [OK] 前端构建完成
)
cd ..

REM 添加并提交
echo.
echo [4/5] 提交代码...
git add -A

REM 生成提交信息带时间戳
set DATE_STR=%date:~0,4%%date:~5,2%%date:~8,2%
set TIME_STR=%time:~0,2%%time:~3,2%
set TIME_STR=%TIME_STR: =0%
set COMMIT_MSG=deploy: %DATE_STR%-%TIME_STR%

git commit -m "%COMMIT_MSG%" 2>nul
if errorlevel 1 (
    echo [提示] 没有更改需要提交
) else (
    echo [OK] 已提交: %COMMIT_MSG%
)

REM 推送
echo.
echo [5/5] 推送到远程...
git push origin main 2>nul || git push -u origin main
if errorlevel 1 (
    echo [错误] 推送失败
    echo 请检查远程仓库权限和网络
    pause
    exit /b 1
)

echo.
echo ========================================
echo [OK] 推送完成！
echo ========================================
echo.
echo 服务器部署命令:
echo   cd /opt/MODstore_deploy
echo   git pull
echo   ./deploy.sh
echo.
pause
