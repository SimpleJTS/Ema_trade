#!/bin/bash
# Binance Futures Bot - Docker一键部署脚本
# 使用方法: bash deploy.sh

set -e

echo "=========================================="
echo "🐳 Binance Futures Bot - Docker部署"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查Docker是否已安装
check_docker() {
    echo "⏳ 检查Docker环境..."
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker未安装${NC}"
        echo "请先安装Docker: curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh"
        exit 1
    fi
    echo -e "${GREEN}✅ Docker已安装: $(docker --version)${NC}"
}

# 检查.env文件
check_env() {
    echo ""
    echo "⏳ 检查配置文件..."
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}⚠️  .env文件不存在，创建模板...${NC}"
        cat > .env << 'EOF'
# 币安API配置
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
BINANCE_TESTNET=false

# Telegram配置
TG_BOT_TOKEN=your_bot_token_here
TG_CHAT_ID=your_chat_id_here

# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db

# 交易参数
DEFAULT_LEVERAGE=10
DEFAULT_STOP_LOSS_PERCENT=2.0
POSITION_SIZE_PERCENT=10.0
MIN_PRICE_CHANGE_PERCENT=30.0

# 振幅过滤
MIN_AMPLITUDE_PERCENT=7.0
AMPLITUDE_CHECK_KLINES=200
EOF
        echo -e "${RED}❌ 请先编辑.env文件，填入你的API密钥和Telegram配置${NC}"
        echo "   使用命令: nano .env"
        exit 1
    fi

    # 检查是否包含默认值
    if grep -q "your_api_key_here" .env; then
        echo -e "${RED}❌ .env文件包含默认值，请先配置API密钥${NC}"
        echo "   使用命令: nano .env"
        exit 1
    fi

    echo -e "${GREEN}✅ 配置文件已存在${NC}"
}

# 创建必要的目录
create_dirs() {
    echo ""
    echo "⏳ 创建数据目录..."
    mkdir -p data logs
    echo -e "${GREEN}✅ 目录已创建${NC}"
}

# 构建Docker镜像
build_image() {
    echo ""
    echo "⏳ 构建Docker镜像（这可能需要2-5分钟）..."
    docker build -t binance-futures-bot:latest .
    echo -e "${GREEN}✅ 镜像构建完成${NC}"
}

# 初始化数据库
init_database() {
    echo ""
    echo "⏳ 初始化数据库..."

    # 检查数据库是否已存在
    if [ -f "data/bot.db" ]; then
        echo -e "${YELLOW}⚠️  数据库已存在，跳过初始化${NC}"

        # 询问是否需要迁移
        read -p "是否执行数据库迁移？(y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "⏳ 执行数据库迁移..."
            docker run --rm \
              -v $(pwd)/data:/app/data \
              binance-futures-bot:latest \
              sqlite3 /app/data/bot.db < /app/migrations/add_leverage_strategy_fields.sql || true
            echo -e "${GREEN}✅ 数据库迁移完成${NC}"
        fi
    else
        # 初始化新数据库
        docker run --rm \
          -v $(pwd)/data:/app/data \
          -v $(pwd)/.env:/app/.env \
          binance-futures-bot:latest \
          python -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"

        # 执行迁移
        echo "⏳ 执行数据库迁移..."
        docker run --rm \
          -v $(pwd)/data:/app/data \
          binance-futures-bot:latest \
          sqlite3 /app/data/bot.db < /app/migrations/add_leverage_strategy_fields.sql || true

        echo -e "${GREEN}✅ 数据库初始化完成${NC}"
    fi
}

# 停止旧容器
stop_old_container() {
    echo ""
    echo "⏳ 检查旧容器..."
    if docker ps -a | grep -q binance-futures-bot; then
        echo "⏳ 停止并删除旧容器..."
        docker stop binance-futures-bot 2>/dev/null || true
        docker rm binance-futures-bot 2>/dev/null || true
        echo -e "${GREEN}✅ 旧容器已清理${NC}"
    else
        echo -e "${GREEN}✅ 无旧容器${NC}"
    fi
}

# 启动容器
start_container() {
    echo ""
    echo "⏳ 启动容器..."
    docker run -d \
      --name binance-futures-bot \
      --restart unless-stopped \
      -p 8000:8000 \
      -v $(pwd)/data:/app/data \
      -v $(pwd)/logs:/app/logs \
      -v $(pwd)/.env:/app/.env \
      -e TZ=Asia/Shanghai \
      binance-futures-bot:latest

    echo -e "${GREEN}✅ 容器已启动${NC}"
}

# 检查容器状态
check_status() {
    echo ""
    echo "⏳ 等待容器启动（10秒）..."
    sleep 10

    if docker ps | grep -q binance-futures-bot; then
        echo -e "${GREEN}✅ 容器运行正常${NC}"
        echo ""
        echo "=========================================="
        echo "🎉 部署成功！"
        echo "=========================================="
        echo ""
        echo "📊 访问Web界面: http://localhost:8000"
        echo ""
        echo "📝 常用命令："
        echo "   查看日志: docker logs -f binance-futures-bot"
        echo "   停止容器: docker stop binance-futures-bot"
        echo "   启动容器: docker start binance-futures-bot"
        echo "   重启容器: docker restart binance-futures-bot"
        echo ""
        echo "📖 详细文档: 查看 DOCKER_DEPLOYMENT.md"
        echo ""

        # 显示最近几行日志
        echo "=========================================="
        echo "📋 最近日志："
        echo "=========================================="
        docker logs --tail 20 binance-futures-bot
    else
        echo -e "${RED}❌ 容器启动失败${NC}"
        echo "查看错误日志: docker logs binance-futures-bot"
        exit 1
    fi
}

# 主流程
main() {
    check_docker
    check_env
    create_dirs
    build_image
    init_database
    stop_old_container
    start_container
    check_status
}

# 执行主流程
main
