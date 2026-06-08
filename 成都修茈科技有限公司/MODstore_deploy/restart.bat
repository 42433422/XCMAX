@echo off
chcp 65001 >nul
REM 与 deploy.bat 相同：切目录、释放端口、装依赖、构建前端、启动（含 --reload）
call "%~dp0deploy.bat"
