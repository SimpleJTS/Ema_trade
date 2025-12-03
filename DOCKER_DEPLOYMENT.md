# 🐳 Docker部署指南（Linux）

## 📋 前置要求

- Linux服务器（Ubuntu 20.04+ / CentOS 7+ / Debian 10+）
- Docker 20.10+
- 至少2GB可用内存
- 至少10GB可用磁盘空间

---

## 🚀 快速部署（5分钟）

### 步骤1：安装Docker（如果未安装）

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# CentOS
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io
sudo systemctl start docker
sudo systemctl enable docker
```

### 步骤2：克隆代码

```bash
cd ~
git clone https://github.com/SimpleJTS/Ema_trade.git
cd Ema_trade/binance-futures-bot
```

### 步骤3：配置环境变量

```bash
# 创建.env配置文件
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

# 修改API密钥（重要！）
nano .env
```

**⚠️ 重要提示**：
- 替换 `your_api_key_here` 为你的币安API Key
- 替换 `your_api_secret_here` 为你的币安API Secret
- 替换 `your_bot_token_here` 为你的Telegram Bot Token
- 替换 `your_chat_id_here` 为你的Telegram Chat ID

### 步骤4：构建Docker镜像

```bash
cd /root/Ema_trade/binance-futures-bot

# 构建镜像（约需2-5分钟）
docker build -t binance-futures-bot:latest .
```

### 步骤5：初始化数据库

```bash
# 创建数据目录
mkdir -p data logs

# 运行临时容器初始化数据库
docker run --rm \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/.env:/app/.env \
  binance-futures-bot:latest \
  python -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"

# 执行数据库迁移
docker run --rm \
  -v $(pwd)/data:/app/data \
  binance-futures-bot:latest \
  sqlite3 /app/data/bot.db < /app/migrations/add_leverage_strategy_fields.sql
```

### 步骤6：启动容器

```bash
# 启动机器人（后台运行）
docker run -d \
  --name binance-futures-bot \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/.env:/app/.env \
  -e TZ=Asia/Shanghai \
  binance-futures-bot:latest

# 查看日志
docker logs -f binance-futures-bot
```

---

## 📝 常用Docker命令

### 容器管理

```bash
# 查看运行中的容器
docker ps

# 查看所有容器（包括停止的）
docker ps -a

# 停止容器
docker stop binance-futures-bot

# 启动容器
docker start binance-futures-bot

# 重启容器
docker restart binance-futures-bot

# 删除容器
docker rm -f binance-futures-bot
```

### 日志查看

```bash
# 实时查看日志
docker logs -f binance-futures-bot

# 查看最近100行日志
docker logs --tail 100 binance-futures-bot

# 查看最近5分钟的日志
docker logs --since 5m binance-futures-bot

# 导出日志到文件
docker logs binance-futures-bot > bot_logs.txt 2>&1
```

### 进入容器调试

```bash
# 进入容器Shell
docker exec -it binance-futures-bot bash

# 在容器内执行命令
docker exec binance-futures-bot python -c "print('Hello')"

# 查看容器内数据库
docker exec -it binance-futures-bot sqlite3 /app/data/bot.db "SELECT * FROM trading_pairs;"
```

### 数据备份与恢复

```bash
# 备份数据库
docker cp binance-futures-bot:/app/data/bot.db ./backup_$(date +%Y%m%d_%H%M%S).db

# 或者直接备份宿主机目录
cp data/bot.db backup_$(date +%Y%m%d_%H%M%S).db

# 恢复数据库
docker cp ./backup_20231202_120000.db binance-futures-bot:/app/data/bot.db
docker restart binance-futures-bot
```

---

## 🔄 更新和重新部署

### 方法1：从Git更新

```bash
# 进入项目目录
cd /root/Ema_trade/binance-futures-bot

# 停止并删除旧容器
docker stop binance-futures-bot
docker rm binance-futures-bot

# 拉取最新代码
git pull origin main

# 备份数据库（重要！）
cp data/bot.db data/bot_backup_$(date +%Y%m%d_%H%M%S).db

# 重新构建镜像
docker build -t binance-futures-bot:latest .

# 启动新容器
docker run -d \
  --name binance-futures-bot \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/.env:/app/.env \
  -e TZ=Asia/Shanghai \
  binance-futures-bot:latest
```

### 方法2：不重建镜像（仅修改配置）

```bash
# 修改配置文件
nano .env

# 重启容器
docker restart binance-futures-bot
```

---

## 🌐 访问Web界面

启动成功后，可通过以下方式访问：

```bash
# 本地访问
http://localhost:8000

# 远程访问（需要防火墙放行8000端口）
http://your_server_ip:8000
```

### 防火墙配置

```bash
# Ubuntu/Debian (UFW)
sudo ufw allow 8000/tcp
sudo ufw reload

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload

# 云服务器还需在安全组规则中开放8000端口
```

---

## 🔒 安全建议

### 1. 使用环境变量管理敏感信息

不要将API密钥硬编码在代码中，始终使用`.env`文件。

### 2. 限制Docker容器权限

```bash
# 使用非root用户运行（推荐）
docker run -d \
  --name binance-futures-bot \
  --restart unless-stopped \
  --user 1000:1000 \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/.env:/app/.env \
  binance-futures-bot:latest
```

### 3. 配置反向代理（Nginx）

```bash
# 安装Nginx
sudo apt-get install -y nginx

# 创建配置文件
sudo nano /etc/nginx/sites-available/trading-bot

# 添加以下内容：
server {
    listen 80;
    server_name your_domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

# 启用配置
sudo ln -s /etc/nginx/sites-available/trading-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 4. 启用HTTPS（可选）

```bash
# 安装Certbot
sudo apt-get install -y certbot python3-certbot-nginx

# 获取SSL证书
sudo certbot --nginx -d your_domain.com
```

---

## 📊 监控和告警

### 查看容器资源使用

```bash
# 查看容器资源使用情况
docker stats binance-futures-bot

# 查看容器详细信息
docker inspect binance-futures-bot
```

### 设置自动重启

```bash
# 容器已配置 --restart unless-stopped
# 即使Docker重启，容器也会自动启动

# 查看重启策略
docker inspect binance-futures-bot | grep -A 3 RestartPolicy
```

### 定时备份（Cron）

```bash
# 编辑crontab
crontab -e

# 添加每天凌晨2点备份
0 2 * * * cp /root/Ema_trade/binance-futures-bot/data/bot.db /root/backups/bot_$(date +\%Y\%m\%d).db

# 添加每周日清理30天前的备份
0 3 * * 0 find /root/backups -name "bot_*.db" -mtime +30 -delete
```

---

## 🐛 故障排查

### 问题1：容器启动失败

```bash
# 查看容器日志
docker logs binance-futures-bot

# 常见原因：
# - .env文件配置错误
# - 端口8000被占用
# - 数据目录权限问题
```

**解决方案**：
```bash
# 检查端口占用
sudo netstat -tulpn | grep 8000
sudo lsof -i :8000

# 修复数据目录权限
sudo chown -R $(whoami):$(whoami) data logs
```

### 问题2：无法连接币安API

```bash
# 检查网络连接
docker exec binance-futures-bot ping -c 3 api.binance.com

# 检查DNS解析
docker exec binance-futures-bot nslookup api.binance.com
```

**解决方案**：
```bash
# 如果是DNS问题，使用Google DNS
docker run -d \
  --name binance-futures-bot \
  --restart unless-stopped \
  --dns 8.8.8.8 \
  --dns 8.8.4.4 \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/.env:/app/.env \
  binance-futures-bot:latest
```

### 问题3：CoinGecko API失败

查看日志中的错误信息：
```bash
docker logs binance-futures-bot | grep -i coingecko
```

**解决方案**：
- CoinGecko免费版限制50次/分钟
- 系统已实现1小时缓存
- 失败时自动使用保守杠杆5x

### 问题4：数据库锁定

```bash
# 错误：database is locked
# 原因：多个进程同时访问数据库

# 解决方案：重启容器
docker restart binance-futures-bot
```

---

## 📦 镜像管理

### 查看镜像

```bash
# 列出所有镜像
docker images

# 查看镜像大小
docker images binance-futures-bot
```

### 清理旧镜像

```bash
# 删除未使用的镜像
docker image prune -a

# 删除特定镜像
docker rmi binance-futures-bot:old
```

### 导出/导入镜像

```bash
# 导出镜像
docker save binance-futures-bot:latest > bot_image.tar

# 导入镜像（在其他服务器）
docker load < bot_image.tar
```

---

## 🔧 高级配置

### 使用自定义网络

```bash
# 创建网络
docker network create trading-network

# 启动容器并连接到网络
docker run -d \
  --name binance-futures-bot \
  --network trading-network \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/.env:/app/.env \
  binance-futures-bot:latest
```

### 资源限制

```bash
# 限制CPU和内存使用
docker run -d \
  --name binance-futures-bot \
  --restart unless-stopped \
  --cpus="1.5" \
  --memory="1g" \
  --memory-swap="1g" \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/.env:/app/.env \
  binance-futures-bot:latest
```

---

## 📞 获取帮助

### 查看日志

```bash
# 应用日志
docker logs -f binance-futures-bot

# 系统日志
docker exec binance-futures-bot tail -f /app/logs/app.log
```

### 数据库查询

```bash
# 查看交易对
docker exec -it binance-futures-bot \
  sqlite3 /app/data/bot.db \
  "SELECT symbol, strategy_type, current_leverage, atr_volatility FROM trading_pairs WHERE is_active=1;"

# 查看持仓
docker exec -it binance-futures-bot \
  sqlite3 /app/data/bot.db \
  "SELECT symbol, side, entry_price, quantity, stop_loss_price, is_partial_closed FROM positions WHERE status='OPEN';"

# 查看交易日志
docker exec -it binance-futures-bot \
  sqlite3 /app/data/bot.db \
  "SELECT * FROM trade_logs ORDER BY created_at DESC LIMIT 10;"
```

---

## ✅ 部署检查清单

- [ ] Docker已安装并运行
- [ ] 代码已克隆到服务器
- [ ] .env文件已配置（API密钥、Telegram等）
- [ ] 数据目录已创建（data、logs）
- [ ] 防火墙已放行8000端口
- [ ] Docker镜像已构建成功
- [ ] 数据库已初始化
- [ ] 数据库迁移已执行
- [ ] 容器已启动并运行
- [ ] Web界面可访问
- [ ] Telegram通知正常工作
- [ ] 日志无严重错误
- [ ] 备份策略已配置

---

## 🎉 完成！

部署完成后，你的交易机器人将：
- ✅ 24/7自动监控币安市场
- ✅ 自动添加涨跌幅≥30%的币种
- ✅ 使用高级策略筛选交易信号
- ✅ 动态调整杠杆（3x-25x）
- ✅ 智能4级止损止盈
- ✅ 部分平仓+追踪止损
- ✅ Telegram实时通知

祝交易顺利！📈🚀
