#!/bin/bash
# MODstore Linux 部署脚本
# 用法: chmod +x deploy.sh && ./deploy.sh
#
# MODSTORE_DEPLOY_LOG_JSON=1 — 额外输出单行 JSON 阶段日志（便于采集与告警解析）

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DEPLOY_SCRIPT_ID="deploy_sh"
if [ -f "${ROOT_DIR}/scripts/lib/deploy_emit.sh" ]; then
  # shellcheck source=scripts/lib/deploy_emit.sh
  . "${ROOT_DIR}/scripts/lib/deploy_emit.sh"
else
  deploy_emit() { :; }
  deploy_emit_summary_json() { :; }
fi

echo "========================================"
echo "   MODstore Linux 部署"
echo "========================================"
echo ""

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

deploy_emit sanity_root_warn started "check_euid"

# 检查是否为 root
if [ "$EUID" -eq 0 ]; then
   echo -e "${RED}[警告] 不建议使用 root 用户运行${NC}"
   deploy_emit sanity_root_warn ok "running_as_root_not_recommended"
   sleep 2
else
   deploy_emit sanity_root_warn ok "non_root"
fi

deploy_emit python_runtime_check started
echo "[1/7] 检查 Python 3.11+..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[错误] 未找到 Python3${NC}"
    echo "请先安装 Python 3.11+"
    deploy_emit python_runtime_check failed "python3_missing exit=1"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}[OK] Python 版本: $PYTHON_VERSION${NC}"
deploy_emit python_runtime_check ok "version=${PYTHON_VERSION}"

deploy_emit env_dotenv started
echo ""
echo "[2/7] 检查 .env 配置..."
cd "${ROOT_DIR}"
if [ ! -f ".env" ]; then
    if [ -f ".env.production" ]; then
        cp .env.production .env
        echo -e "${YELLOW}[提示] 已从 .env.production 复制 .env，请编辑修改配置${NC}"
        echo "必须修改: JWT_SECRET, ADMIN_RECHARGE_TOKEN, CORS_ORIGINS, PUBLIC_ORIGIN"
        deploy_emit env_dotenv failed "copied_from_production_needs_edit exit=1"
        exit 1
    else
        echo -e "${RED}[错误] 未找到 .env 或 .env.production${NC}"
        deploy_emit env_dotenv failed "missing_env exit=1"
        exit 1
    fi
fi
echo -e "${GREEN}[OK] .env 存在${NC}"
deploy_emit env_dotenv ok ".env_present"

deploy_emit venv_prepare started
echo ""
echo "[3/7] 创建虚拟环境..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}[OK] 虚拟环境已创建${NC}"
    deploy_emit venv_prepare ok "created"
else
    echo -e "${GREEN}[OK] 虚拟环境已存在${NC}"
    deploy_emit venv_prepare ok "existing"
fi

# 激活虚拟环境
source .venv/bin/activate

deploy_emit pip_install started
echo ""
echo "[4/7] 安装 Python 依赖..."
pip install -q --upgrade pip
pip install -q fastapi "uvicorn[standard]" python-multipart httpx sqlalchemy PyJWT bcrypt python-dotenv python-alipay-sdk
pip install -q -e ".[web,knowledge]"
echo -e "${GREEN}[OK] 依赖安装完成${NC}"
deploy_emit pip_install ok

deploy_emit frontend_vite_build started
echo ""
echo "[5/7] 构建前端..."
if command -v npm &> /dev/null; then
    cd market
    if [ ! -d "node_modules" ]; then
        echo "[提示] 安装 npm 依赖..."
        npm ci
    fi
    if npm run build; then
        echo -e "${GREEN}[OK] 前端构建完成${NC}"
        deploy_emit frontend_vite_build ok
    else
        echo -e "${RED}[警告] 前端构建失败${NC}"
        deploy_emit frontend_vite_build failed "npm_run_build_failed"
    fi
    cd ..
else
    echo -e "${YELLOW}[跳过] 未找到 npm，跳过前端构建${NC}"
    deploy_emit frontend_vite_build skipped "npm_not_found"
fi

deploy_emit db_schema_init started
echo ""
echo "[6/7] 初始化数据库..."
python3 -c "
from modstore_server.models import init_db
init_db()
print('数据库初始化完成')
"
deploy_emit db_schema_init ok

deploy_emit email_config_probe started
echo ""
echo "[6.5/7] 自检邮件服务（SMTP 凭证 / DEBUG 模式）..."
EMAIL_CHECK_OUTPUT=$(set -a; [ -f .env ] && . .env; set +a; python3 -c "
import json
from modstore_server.email_service import email_status
s = email_status()
print(json.dumps(s, ensure_ascii=False))
")
EMAIL_MODE=$(echo "$EMAIL_CHECK_OUTPUT" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('mode',''))")
case "$EMAIL_MODE" in
  smtp)
    echo -e "${GREEN}[OK] 邮件服务已配置 (SMTP)${NC}"
    deploy_emit email_config_probe ok "mode=smtp"
    ;;
  debug)
    echo -e "${YELLOW}[提示] MODSTORE_EMAIL_DEBUG=1，验证码会打印到控制台而非真实发信${NC}"
    deploy_emit email_config_probe ok "mode=debug"
    ;;
  unconfigured)
    echo -e "${RED}[警告] 邮件服务未配置或仍是占位符（如 your-qq-smtp-auth-code / CHANGE_ME）${NC}"
    echo "  → 注册 / 找回密码 / 验证码登录会失败"
    echo "  解决方案三选一："
    echo "    A. 编辑 .env 把 MODSTORE_SMTP_USER/MODSTORE_SMTP_PASSWORD 改为真实凭证"
    echo "       （QQ邮箱：mail.qq.com → 设置 → 账户 → 开 SMTP → 生成授权码）"
    echo "    B. 临时调试：在 .env 里设 MODSTORE_EMAIL_DEBUG=1，验证码打印到控制台"
    echo "    C. 已确认部署后再配置：直接继续启动；启动后管理员可在 /api/admin/email/test 测试"
    deploy_emit email_config_probe ok "mode=unconfigured_warn"
    ;;
esac

deploy_emit deploy_instructions started
echo ""
echo "[7/7] 启动服务..."
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  部署完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "启动命令:"
echo "  source .venv/bin/activate"
echo "  python -m uvicorn modstore_server.app:app --host 0.0.0.0 --port 8765"
echo ""
echo "或使用 systemd 后台运行:"
echo "  sudo systemctl enable --now modstore"
echo ""
echo "访问地址:"
echo "  前端: http://你的服务器IP:8765/market"
echo "  API文档: http://你的服务器IP:8765/docs"
echo ""
deploy_emit deploy_instructions ok "awaiting_optional_uvicorn_start"
deploy_emit_summary_json true true false false || true

# 询问是否立即启动
read -p "是否立即启动服务? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    deploy_emit uvicorn_start started
    # 多 worker 安全校验
    WORKERS=${MODSTORE_UVICORN_WORKERS:-1}
    if [ "$WORKERS" -gt 1 ]; then
        BACKEND=${PAYMENT_BACKEND:-python}
        if [ "$BACKEND" != "java" ]; then
            echo -e "${RED}[错误] MODSTORE_UVICORN_WORKERS=$WORKERS > 1 时必须设置 PAYMENT_BACKEND=java${NC}"
            echo "  原因：Python 侧防重放 nonce (_ReplayGuard) 是进程内存，多 worker 下无法共享。"
            echo "  解决：在 .env 或环境变量中设置 PAYMENT_BACKEND=java，由 Java 服务以 Redis 实现 nonce。"
            deploy_emit uvicorn_start failed "workers_without_java_payment_backend exit=1"
            exit 1
        fi
    fi
    echo "正在启动 (workers=$WORKERS)..."
    deploy_emit_summary_json true true false false || true
    python -m uvicorn modstore_server.app:app --host 0.0.0.0 --port 8765 --workers "$WORKERS"
fi
