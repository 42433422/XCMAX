#!/bin/bash
# MODstore Git 推送 + 构建脚本 (Linux/macOS)
# 用法: chmod +x git-push.sh && ./git-push.sh

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   MODstore Git 推送 + 构建${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查 git
if ! command -v git &> /dev/null; then
    echo -e "${RED}[错误] 未找到 Git，请先安装${NC}"
    exit 1
fi

# 初始化仓库（如果没有）
if [ ! -d ".git" ]; then
    echo -e "${YELLOW}[1/5] 初始化 Git 仓库...${NC}"
    git init
    git branch -M main
    echo -e "${GREEN}[OK] 已初始化${NC}"
else
    echo -e "${GREEN}[1/5] Git 仓库已存在${NC}"
fi

# 检查远程仓库
echo ""
echo -e "${YELLOW}[2/5] 检查远程仓库...${NC}"
if ! git remote get-url origin &> /dev/null; then
    echo -e "${YELLOW}[提示] 未配置远程仓库${NC}"
    read -p "请输入远程仓库地址: " REMOTE_URL
    if [ -z "$REMOTE_URL" ]; then
        echo -e "${RED}[错误] 地址不能为空${NC}"
        exit 1
    fi
    git remote add origin "$REMOTE_URL"
fi
git remote -v

# 构建前端
echo ""
echo -e "${YELLOW}[3/5] 构建前端...${NC}"
cd market
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}[提示] 安装 npm 依赖...${NC}"
    npm ci
fi

if npm run build; then
    echo -e "${GREEN}[OK] 前端构建完成${NC}"
else
    echo -e "${RED}[警告] 构建失败，继续推送源代码${NC}"
fi
cd ..

# 添加并提交
echo ""
echo -e "${YELLOW}[4/5] 提交代码...${NC}"
git add -A

# 生成提交信息带时间戳
DATE_STR=$(date +%Y%m%d)
TIME_STR=$(date +%H%M)
COMMIT_MSG="deploy: ${DATE_STR}-${TIME_STR}"

if git commit -m "$COMMIT_MSG"; then
    echo -e "${GREEN}[OK] 已提交: $COMMIT_MSG${NC}"
else
    echo -e "${YELLOW}[提示] 没有更改需要提交${NC}"
fi

# 推送
echo ""
echo -e "${YELLOW}[5/5] 推送到远程...${NC}"
if git push origin main 2>/dev/null || git push -u origin main; then
    echo -e "${GREEN}[OK] 推送完成${NC}"
else
    echo -e "${RED}[错误] 推送失败${NC}"
    echo "请检查远程仓库权限和网络"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   推送完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "服务器部署命令:"
echo -e "${BLUE}  cd /opt/MODstore_deploy${NC}"
echo -e "${BLUE}  git pull${NC}"
echo -e "${BLUE}  ./deploy.sh${NC}"
echo ""
