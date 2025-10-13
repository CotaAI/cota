# 部署指南

COTA框架支持多种部署方式，从开发环境到生产环境，从单机部署到集群部署。本指南将详细介绍各种部署方案和最佳实践。

## 📋 部署概览

### 支持的部署方式

```mermaid
graph TD
    Deployment[COTA部署] --> Development[开发环境]
    Deployment --> Production[生产环境]
    
    Development --> Local[本地开发]
    Development --> DevServer[开发服务器]
    
    Production --> SingleNode[单节点部署]
    Production --> Cluster[集群部署]
    Production --> Container[容器化部署]
    
    Local --> Poetry[Poetry环境]
    Local --> Venv[虚拟环境]
    
    DevServer --> TestServer[测试服务器]
    DevServer --> StagingServer[预发布环境]
    
    SingleNode --> SystemD[SystemD服务]
    SingleNode --> ProcessManager[进程管理器]
    
    Cluster --> LoadBalancer[负载均衡]
    Cluster --> HealthCheck[健康检查]
    
    Container --> Docker[Docker容器]
    Container --> Kubernetes[K8s集群]
```

### 系统要求

**最低要求**:
- Python 3.8+
- 内存: 512MB
- 磁盘: 1GB
- CPU: 1核心

**推荐配置**:
- Python 3.10+
- 内存: 2GB+
- 磁盘: 10GB+
- CPU: 2核心+

## 🔧 开发环境部署

### 方式一：使用Poetry（推荐）

**1. 安装Poetry**
```bash
# macOS/Linux
curl -sSL https://install.python-poetry.org | python3 -

# Windows (PowerShell)
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

**2. 克隆项目**
```bash
git clone https://github.com/CotaAI/cota.git
cd cota
```

**3. 安装依赖**
```bash
# 安装项目依赖
poetry install

# 激活虚拟环境
poetry shell
```

**4. 配置智能体**
```bash
# 创建项目目录
poetry run cota init

# 编辑配置文件
cd cota_projects/simplebot
vim agent.yml
vim endpoints.yml
```

**5. 启动服务**
```bash
# 开发模式启动
poetry run cota run \
  --config=cota_projects/simplebot \
  --channel=websocket \
  --host=localhost \
  --port=5005 \
  --debug
```

### 方式二：使用pip和venv

**1. 创建虚拟环境**
```bash
python -m venv cota_env
source cota_env/bin/activate  # Linux/macOS
# 或
cota_env\Scripts\activate     # Windows
```

**2. 安装COTA**
```bash
pip install -r requirements.txt
pip install -e .
```

**3. 启动服务**
```bash
python -m cota run --config=./bots/simplebot --debug
```

### 开发环境配置

**环境变量设置** (`.env`文件):
```bash
# 开发环境配置
COTA_ENV=development
COTA_DEBUG=true
COTA_LOG_LEVEL=DEBUG

# 数据库配置
DATABASE_URL=sqlite:///./dev.db

# LLM配置 
OPENAI_API_KEY=your_openai_key
OPENAI_BASE_URL=https://api.openai.com/v1

# 其他配置
COTA_HOST=localhost
COTA_PORT=5005
```

**开发启动脚本** (`dev_start.sh`):
```bash
#!/bin/bash
set -e

echo "启动COTA开发环境..."

# 加载环境变量
if [ -f .env ]; then
    export $(cat .env | xargs)
fi

# 检查依赖
poetry check

# 启动开发服务器
poetry run cota run \
  --config=bots/simplebot \
  --channel=websocket \
  --host=${COTA_HOST:-localhost} \
  --port=${COTA_PORT:-5005} \
  --debug \
  --log=DEBUG

echo "开发服务器已启动: http://${COTA_HOST:-localhost}:${COTA_PORT:-5005}"
```

## 🚀 生产环境部署

### 单节点生产部署

**1. 服务器准备**
```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装Python和必要工具
sudo apt install python3.10 python3.10-venv python3-pip git nginx -y

# 创建应用用户
sudo useradd -m -s /bin/bash cota
sudo usermod -aG sudo cota
```

**2. 应用部署**
```bash
# 切换到应用用户
sudo su - cota

# 克隆代码
git clone https://github.com/CotaAI/cota.git
cd cota

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install -e .
```

**3. 配置文件**

**生产环境配置** (`production.env`):
```bash
# 生产环境配置
COTA_ENV=production
COTA_DEBUG=false
COTA_LOG_LEVEL=INFO

# 服务配置
COTA_HOST=0.0.0.0
COTA_PORT=5005
COTA_WORKERS=4

# 数据库配置
DATABASE_URL=postgresql://cota_user:password@localhost/cota_db

# Redis配置 (用于缓存和会话)
REDIS_URL=redis://localhost:6379/0

# SSL配置
SSL_CERT_PATH=/etc/ssl/certs/cota.crt
SSL_KEY_PATH=/etc/ssl/private/cota.key

# LLM配置
OPENAI_API_KEY=${OPENAI_API_KEY}
OPENAI_BASE_URL=https://api.openai.com/v1

# 安全配置
SECRET_KEY=your_secret_key_here
JWT_SECRET=your_jwt_secret_here
```

**4. SystemD服务配置**

创建服务文件 `/etc/systemd/system/cota.service`:
```ini
[Unit]
Description=COTA Intelligent Agent Platform
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=cota
Group=cota
WorkingDirectory=/home/cota/cota
Environment=PATH=/home/cota/cota/venv/bin
EnvironmentFile=/home/cota/cota/production.env
ExecStart=/home/cota/cota/venv/bin/cota run \
    --config=/home/cota/cota/bots/simplebot \
    --channel=websocket \
    --host=0.0.0.0 \
    --port=5005
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=5
StartLimitInterval=60s
StartLimitBurst=3

# 安全配置
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/home/cota/cota/logs
ReadWritePaths=/tmp

# 资源限制
MemoryLimit=2G
CPUQuota=200%

[Install]
WantedBy=multi-user.target
```

**5. 启动和管理服务**
```bash
# 重新加载systemd配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start cota

# 设置开机自启
sudo systemctl enable cota

# 查看服务状态
sudo systemctl status cota

# 查看日志
sudo journalctl -u cota -f

# 重启服务
sudo systemctl restart cota
```

### Nginx反向代理配置

**Nginx配置** (`/etc/nginx/sites-available/cota`):
```nginx
upstream cota_backend {
    server 127.0.0.1:5005;
    # 如果有多个实例
    # server 127.0.0.1:5006;
    # server 127.0.0.1:5007;
}

server {
    listen 80;
    server_name your_domain.com;
    
    # 重定向到HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your_domain.com;
    
    # SSL配置
    ssl_certificate /etc/ssl/certs/your_domain.crt;
    ssl_certificate_key /etc/ssl/private/your_domain.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
    # 安全头
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000" always;
    
    # 日志配置
    access_log /var/log/nginx/cota_access.log;
    error_log /var/log/nginx/cota_error.log;
    
    # 静态文件
    location /static/ {
        alias /home/cota/cota/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # WebSocket支持
    location /ws {
        proxy_pass http://cota_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
    
    # API接口
    location /api/ {
        proxy_pass http://cota_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时配置
        proxy_connect_timeout 30s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # 缓冲配置
        proxy_buffering on;
        proxy_buffer_size 8k;
        proxy_buffers 8 8k;
    }
    
    # 主页面
    location / {
        proxy_pass http://cota_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**启用Nginx配置**:
```bash
sudo ln -s /etc/nginx/sites-available/cota /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 生产环境启动脚本

**生产启动脚本** (`production_start.sh`):
```bash
#!/bin/bash
set -e

# 配置
APP_DIR="/home/cota/cota"
USER="cota"
CONFIG_DIR="$APP_DIR/bots/simplebot"
LOG_DIR="$APP_DIR/logs"
PID_FILE="$APP_DIR/cota.pid"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 日志函数
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" >&2
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# 检查环境
check_environment() {
    log "检查部署环境..."
    
    # 检查用户
    if [ "$(whoami)" != "$USER" ]; then
        error "请使用 $USER 用户运行此脚本"
        exit 1
    fi
    
    # 检查目录
    if [ ! -d "$APP_DIR" ]; then
        error "应用目录不存在: $APP_DIR"
        exit 1
    fi
    
    # 检查配置
    if [ ! -f "$CONFIG_DIR/agent.yml" ]; then
        error "配置文件不存在: $CONFIG_DIR/agent.yml"
        exit 1
    fi
    
    # 创建日志目录
    mkdir -p "$LOG_DIR"
    
    log "环境检查通过"
}

# 更新代码
update_code() {
    log "更新应用代码..."
    cd "$APP_DIR"
    
    # 备份当前版本
    BACKUP_DIR="$APP_DIR/backup/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # 拉取最新代码
    git fetch origin
    CURRENT_COMMIT=$(git rev-parse HEAD)
    git pull origin main
    NEW_COMMIT=$(git rev-parse HEAD)
    
    if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
        log "代码已是最新版本"
    else
        log "代码更新成功: $CURRENT_COMMIT -> $NEW_COMMIT"
    fi
}

# 停止旧服务
stop_service() {
    log "停止现有服务..."
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            log "停止进程 PID: $PID"
            kill -TERM "$PID"
            
            # 等待进程退出
            for i in {1..30}; do
                if ! ps -p "$PID" > /dev/null 2>&1; then
                    log "服务已停止"
                    break
                fi
                sleep 1
            done
            
            # 强制结束
            if ps -p "$PID" > /dev/null 2>&1; then
                warn "强制结束进程"
                kill -9 "$PID"
            fi
        fi
        rm -f "$PID_FILE"
    fi
    
    # 查找并清理其他cota进程
    COTA_PIDS=$(pgrep -f "cota run" | grep -v "$$" || true)
    if [ -n "$COTA_PIDS" ]; then
        warn "发现其他COTA进程，正在清理..."
        echo "$COTA_PIDS" | xargs kill -TERM
        sleep 5
        echo "$COTA_PIDS" | xargs kill -9 2>/dev/null || true
    fi
}

# 启动新服务
start_service() {
    log "启动新服务..."
    cd "$APP_DIR"
    
    # 加载环境变量
    if [ -f "production.env" ]; then
        set -a
        source production.env
        set +a
    fi
    
    # 启动服务
    nohup venv/bin/cota run \
        --config="$CONFIG_DIR" \
        --channel=websocket \
        --host=0.0.0.0 \
        --port=5005 \
        > "$LOG_DIR/cota.log" 2>&1 &
    
    echo $! > "$PID_FILE"
    
    # 等待服务启动
    sleep 5
    
    # 检查服务状态
    if ps -p "$(cat $PID_FILE)" > /dev/null 2>&1; then
        log "服务启动成功 PID: $(cat $PID_FILE)"
        log "日志文件: $LOG_DIR/cota.log"
        
        # 检查服务响应
        if curl -f http://localhost:5005/version > /dev/null 2>&1; then
            log "服务健康检查通过"
        else
            warn "服务健康检查失败，请检查日志"
        fi
    else
        error "服务启动失败，请检查日志"
        tail -50 "$LOG_DIR/cota.log"
        exit 1
    fi
}

# 主函数
main() {
    log "开始部署COTA生产环境..."
    
    check_environment
    stop_service
    update_code
    start_service
    
    log "部署完成！"
    log "访问地址: http://localhost:5005"
    log "版本信息: $(curl -s http://localhost:5005/version | grep version || echo '获取失败')"
}

# 信号处理
trap 'error "部署被中断"; exit 1' INT TERM

# 运行主函数
main "$@"
```

## 🐳 容器化部署

### Docker部署

**1. Dockerfile**
```dockerfile
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY pyproject.toml poetry.lock* ./
COPY . .

# 安装Poetry
RUN pip install poetry

# 配置Poetry
RUN poetry config virtualenvs.create false

# 安装依赖
RUN poetry install --no-dev --no-interaction --no-ansi

# 创建非root用户
RUN useradd --create-home --shell /bin/bash cota
RUN chown -R cota:cota /app
USER cota

# 健康检查
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5005/version || exit 1

# 暴露端口
EXPOSE 5005

# 启动命令
CMD ["cota", "run", \
     "--config=/app/bots/simplebot", \
     "--channel=websocket", \
     "--host=0.0.0.0", \
     "--port=5005"]
```

**2. Docker Compose配置**
```yaml
version: '3.8'

services:
  cota:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "5005:5005"
    environment:
      - COTA_ENV=production
      - DATABASE_URL=postgresql://cota:password@postgres:5432/cota
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - ./logs:/app/logs
      - ./bots:/app/bots:ro
    depends_on:
      - postgres
      - redis
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5005/version"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "1.0"

  postgres:
    image: postgres:14
    environment:
      - POSTGRES_DB=cota
      - POSTGRES_USER=cota
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/ssl:ro
    depends_on:
      - cota
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
```

**3. 构建和运行**
```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f cota

# 停止服务
docker-compose down
```

### Kubernetes部署

**1. 部署配置** (`k8s-deployment.yaml`):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cota-deployment
  labels:
    app: cota
spec:
  replicas: 3
  selector:
    matchLabels:
      app: cota
  template:
    metadata:
      labels:
        app: cota
    spec:
      containers:
      - name: cota
        image: cotaai/cota:latest
        ports:
        - containerPort: 5005
        env:
        - name: COTA_ENV
          value: "production"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: cota-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: cota-config
              key: redis-url
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /version
            port: 5005
          initialDelaySeconds: 30
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /version
            port: 5005
          initialDelaySeconds: 5
          periodSeconds: 10
        volumeMounts:
        - name: config-volume
          mountPath: /app/bots
          readOnly: true
      volumes:
      - name: config-volume
        configMap:
          name: cota-bot-config

---
apiVersion: v1
kind: Service
metadata:
  name: cota-service
spec:
  selector:
    app: cota
  ports:
  - protocol: TCP
    port: 80
    targetPort: 5005
  type: LoadBalancer
```

**2. 应用部署**
```bash
# 创建命名空间
kubectl create namespace cota

# 应用配置
kubectl apply -f k8s-deployment.yaml -n cota

# 查看部署状态
kubectl get pods -n cota
kubectl get services -n cota

# 查看日志
kubectl logs -f deployment/cota-deployment -n cota
```

## 📊 监控和日志

### 监控配置

**Prometheus监控** (`prometheus.yml`):
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'cota'
    static_configs:
      - targets: ['localhost:5005']
    metrics_path: /metrics
    scrape_interval: 15s
```

**Grafana仪表板**：
- 请求QPS和响应时间
- 错误率和成功率
- 内存和CPU使用率
- 活跃会话数量

### 日志管理

**日志配置** (`logging.conf`):
```ini
[loggers]
keys=root,cota

[handlers] 
keys=consoleHandler,fileHandler,rotatingHandler

[formatters]
keys=simpleFormatter,detailFormatter

[logger_root]
level=INFO
handlers=consoleHandler

[logger_cota]
level=INFO
handlers=rotatingHandler
qualname=cota
propagate=0

[handler_consoleHandler]
class=StreamHandler
level=INFO
formatter=simpleFormatter
args=(sys.stdout,)

[handler_fileHandler]
class=FileHandler
level=INFO
formatter=detailFormatter
args=('/app/logs/cota.log',)

[handler_rotatingHandler]
class=handlers.RotatingFileHandler
level=INFO
formatter=detailFormatter
args=('/app/logs/cota.log', 'a', 10485760, 5)

[formatter_simpleFormatter]
format=%(asctime)s - %(name)s - %(levelname)s - %(message)s

[formatter_detailFormatter]
format=%(asctime)s - %(name)s - %(levelname)s - %(pathname)s:%(lineno)d - %(funcName)s - %(message)s
```

**ELK Stack日志收集**：
- Filebeat收集日志
- Logstash处理和过滤
- Elasticsearch存储和检索
- Kibana可视化分析

## 🔧 性能优化

### 生产优化配置

**Python优化**：
```bash
# 启用优化模式
export PYTHONOPTIMIZE=2

# 禁用调试信息
export PYTHONDONTWRITEBYTECODE=1

# 设置内存优化
export PYTHONMALLOC=malloc
```

**系统优化**：
```bash
# 调整文件描述符限制
echo "cota soft nofile 65536" >> /etc/security/limits.conf
echo "cota hard nofile 65536" >> /etc/security/limits.conf

# 调整内核参数
echo "net.core.somaxconn = 65535" >> /etc/sysctl.conf
echo "net.ipv4.tcp_max_syn_backlog = 65535" >> /etc/sysctl.conf
sysctl -p
```

### 缓存和数据库优化

**Redis配置优化**：
```redis
# 内存策略
maxmemory 2gb
maxmemory-policy allkeys-lru

# 持久化配置
save 900 1
save 300 10
save 60 10000

# 网络配置
tcp-keepalive 300
timeout 0
```

**PostgreSQL优化**：
```sql
-- 连接数配置
ALTER SYSTEM SET max_connections = 200;

-- 内存配置
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';

-- 查询优化
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET seq_page_cost = 1.0;
```

## 🔐 安全配置

### SSL/TLS配置

**生成自签名证书**（开发环境）：
```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes
```

**Let's Encrypt证书**（生产环境）：
```bash
# 安装certbot
sudo apt install certbot python3-certbot-nginx

# 申请证书
sudo certbot --nginx -d your-domain.com

# 自动续期
sudo crontab -e
0 12 * * * /usr/bin/certbot renew --quiet
```

### 防火墙配置

```bash
# 配置UFW防火墙
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 443
sudo ufw allow 5005/tcp  # COTA端口

# 限制连接频率
sudo ufw limit ssh
```

### 环境安全

```bash
# 设置文件权限
chmod 600 production.env
chmod 600 /etc/ssl/private/cota.key
chmod 644 /etc/ssl/certs/cota.crt

# 设置目录权限
chown -R cota:cota /home/cota/cota
chmod -R 755 /home/cota/cota
```

通过本指南，你可以在各种环境中成功部署COTA，从开发测试到生产运营，都有相应的最佳实践可以参考。
