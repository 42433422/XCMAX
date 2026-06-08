# 与 start_with_alipay.py 相同逻辑：加载 .env、按需注入 keys/*.pem，再启动服务。
cd $PSScriptRoot
if (Test-Path .\.venv\Scripts\Activate.ps1) {
    & .\.venv\Scripts\Activate.ps1
}
python start_with_alipay.py
