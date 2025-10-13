# 配置管理

COTA框架提供了灵活的配置管理系统，支持多环境配置、安全配置、性能优化等高级特性。本文档详细介绍如何进行生产级配置管理。

## 📋 配置架构

### 配置层次结构

```mermaid
graph TD
    Config[配置管理] --> Environment[环境配置]
    Config --> Security[安全配置]
    Config --> Performance[性能配置]
    Config --> Monitor[监控配置]
    
    Environment --> Development[开发环境]
    Environment --> Staging[测试环境]  
    Environment --> Production[生产环境]
    
    Security --> SSL[SSL/TLS]
    Security --> Auth[认证授权]
    Security --> Firewall[防火墙]
    
    Performance --> LoadBalance[负载均衡]
    Performance --> Cache[缓存策略]
    Performance --> Database[数据库优化]
    
    Monitor --> Logging[日志管理]
    Monitor --> Metrics[指标监控]
    Monitor --> Alerts[告警配置]
```

### 配置文件结构

```
cota_config/
├── environments/              # 环境配置
│   ├── development.env
│   ├── staging.env
│   └── production.env
├── ssl/                      # SSL证书
│   ├── certificates/
│   └── private_keys/
├── nginx/                    # Nginx配置
│   ├── sites-available/
│   └── ssl.conf
├── supervisor/               # 进程管理
│   └── cota.conf
├── systemd/                  # SystemD服务
│   └── cota.service
├── monitoring/               # 监控配置
│   ├── prometheus.yml
│   ├── grafana/
│   └── alertmanager.yml
└── scripts/                  # 部署脚本
    ├── deploy.sh
    ├── backup.sh
    └── health_check.sh
```

## 🔐 SSL/TLS配置

### 证书管理

**生产环境SSL配置**：
```bash
# 1. 创建SSL目录
mkdir -p /etc/cota/ssl/{certs,private}
chmod 700 /etc/cota/ssl/private

# 2. 申请Let's Encrypt证书
certbot certonly --standalone \
  -d your-domain.com \
  -d api.your-domain.com \
  --email admin@your-domain.com \
  --agree-tos

# 3. 复制证书到COTA目录
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem /etc/cota/ssl/certs/
cp /etc/letsencrypt/live/your-domain.com/privkey.pem /etc/cota/ssl/private/

# 4. 设置权限
chown -R cota:cota /etc/cota/ssl/
chmod 644 /etc/cota/ssl/certs/*
chmod 600 /etc/cota/ssl/private/*
```

**SSL配置文件** (`ssl_config.yml`):
```yaml
ssl:
  enabled: true
  cert_path: "/etc/cota/ssl/certs/fullchain.pem"
  key_path: "/etc/cota/ssl/private/privkey.pem"
  protocols:
    - "TLSv1.2"
    - "TLSv1.3"
  ciphers: "ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384"
  prefer_server_ciphers: true
  session_timeout: 1d
  session_cache: "shared:SSL:50m"
```

**COTA启动SSL配置**：
```bash
# 启动带SSL的COTA服务
cota run \
  --config=/opt/cota/config \
  --ssl-cert=/etc/cota/ssl/certs/fullchain.pem \
  --ssl-key=/etc/cota/ssl/private/privkey.pem \
  --host=0.0.0.0 \
  --port=443
```

**自动证书更新脚本** (`renew_ssl.sh`):
```bash
#!/bin/bash
set -e

LOG_FILE="/var/log/cota/ssl_renewal.log"
COTA_SERVICE="cota"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# 更新证书
log "开始更新SSL证书..."
if certbot renew --quiet; then
    log "证书更新成功"
    
    # 复制新证书
    cp /etc/letsencrypt/live/your-domain.com/fullchain.pem /etc/cota/ssl/certs/
    cp /etc/letsencrypt/live/your-domain.com/privkey.pem /etc/cota/ssl/private/
    
    # 重启服务
    log "重启COTA服务..."
    systemctl reload nginx
    systemctl restart "$COTA_SERVICE"
    
    log "SSL证书更新完成"
else
    log "ERROR: 证书更新失败"
    exit 1
fi
```

### HSTS和安全头配置

**Nginx安全头配置**：
```nginx
# 安全头配置
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
add_header X-Frame-Options DENY always;
add_header X-Content-Type-Options nosniff always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';" always;

# 隐藏服务器信息
server_tokens off;
```

## ⚖️ 负载均衡配置

### Nginx负载均衡

**多实例负载均衡** (`nginx.conf`):
```nginx
# 上游服务器定义
upstream cota_cluster {
    # 负载均衡方法
    least_conn;  # 最少连接数
    
    # COTA实例
    server 127.0.0.1:5005 weight=3 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:5006 weight=3 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:5007 weight=2 max_fails=3 fail_timeout=30s;
    
    # 备用服务器
    server 127.0.0.1:5008 backup;
    
    # 健康检查
    keepalive 32;
}

server {
    listen 80;
    listen 443 ssl http2;
    server_name api.your-domain.com;
    
    # SSL配置
    ssl_certificate /etc/cota/ssl/certs/fullchain.pem;
    ssl_certificate_key /etc/cota/ssl/private/privkey.pem;
    
    # 负载均衡配置
    location / {
        proxy_pass http://cota_cluster;
        
        # 代理头设置
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 连接保活
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        
        # 超时设置
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # 重试设置
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 10s;
    }
    
    # WebSocket支持
    location /ws {
        proxy_pass http://cota_cluster;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
    
    # 健康检查端点
    location /health {
        proxy_pass http://cota_cluster/version;
        access_log off;
    }
}
```

### HAProxy负载均衡

**HAProxy配置** (`haproxy.cfg`):
```
global
    daemon
    log 127.0.0.1:514 local0
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin
    stats timeout 30s
    user haproxy
    group haproxy

defaults
    mode http
    log global
    option httplog
    option dontlognull
    timeout connect 5000
    timeout client 50000
    timeout server 50000
    errorfile 400 /etc/haproxy/errors/400.http
    errorfile 403 /etc/haproxy/errors/403.http
    errorfile 408 /etc/haproxy/errors/408.http
    errorfile 500 /etc/haproxy/errors/500.http
    errorfile 502 /etc/haproxy/errors/502.http
    errorfile 503 /etc/haproxy/errors/503.http
    errorfile 504 /etc/haproxy/errors/504.http

# 统计页面
listen stats
    bind *:8404
    stats enable
    stats uri /stats
    stats refresh 30s
    stats admin if TRUE

# COTA前端
frontend cota_frontend
    bind *:80
    bind *:443 ssl crt /etc/ssl/certs/cota.pem
    redirect scheme https if !{ ssl_fc }
    
    # 安全头
    http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains"
    http-response set-header X-Frame-Options DENY
    http-response set-header X-Content-Type-Options nosniff
    
    default_backend cota_servers

# COTA后端服务器
backend cota_servers
    balance roundrobin
    option httpchk GET /version
    
    server cota1 127.0.0.1:5005 check inter 30s rise 2 fall 3
    server cota2 127.0.0.1:5006 check inter 30s rise 2 fall 3
    server cota3 127.0.0.1:5007 check inter 30s rise 2 fall 3 backup
```

### 会话粘性配置

**基于IP的会话粘性**：
```nginx
upstream cota_cluster {
    ip_hash;  # 基于客户端IP的哈希
    
    server 127.0.0.1:5005;
    server 127.0.0.1:5006;
    server 127.0.0.1:5007;
}
```

**基于Cookie的会话粘性**：
```nginx
map $cookie_cota_session $upstream {
    ~^(?P<session_id>[a-f0-9]+) $session_id;
    default "";
}

upstream cota_cluster {
    hash $upstream consistent;
    
    server 127.0.0.1:5005;
    server 127.0.0.1:5006;
    server 127.0.0.1:5007;
}
```

## 💾 数据库配置

### PostgreSQL配置

**连接池配置** (`database.yml`):
```yaml
database:
  type: "postgresql"
  host: "localhost"
  port: 5432
  database: "cota_production"
  username: "cota_user"
  password: "${DB_PASSWORD}"
  
  # 连接池设置
  pool:
    min_size: 5
    max_size: 20
    max_queries: 50000
    max_idle: 300
    
  # 性能设置
  options:
    application_name: "cota"
    connect_timeout: 10
    command_timeout: 60
    server_settings:
      shared_preload_libraries: "pg_stat_statements"
      max_connections: 200
      shared_buffers: "256MB"
      effective_cache_size: "1GB"
```

**PostgreSQL优化配置** (`postgresql.conf`):
```conf
# 连接设置
max_connections = 200
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100

# 性能优化
random_page_cost = 1.1
seq_page_cost = 1.0
effective_io_concurrency = 200

# WAL设置
wal_level = replica
max_wal_senders = 3
archive_mode = on
archive_command = 'cp %p /backup/wal/%f'

# 日志设置
log_min_duration_statement = 1000
log_checkpoints = on
log_connections = on
log_disconnections = on
log_lock_waits = on
```

### Redis配置

**Redis缓存配置** (`redis.conf`):
```conf
# 基本设置
bind 127.0.0.1
port 6379
timeout 300
keepalive 300

# 内存设置
maxmemory 2gb
maxmemory-policy allkeys-lru
maxmemory-samples 5

# 持久化设置
save 900 1
save 300 10
save 60 10000

# AOF设置
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec

# 性能设置
tcp-backlog 511
databases 16
```

**Redis集群配置**：
```bash
# Redis集群部署脚本
#!/bin/bash

# 创建集群节点
for port in 7000 7001 7002 7003 7004 7005; do
    mkdir -p /etc/redis/cluster/$port
    cat > /etc/redis/cluster/$port/redis.conf <<EOF
port $port
cluster-enabled yes
cluster-config-file nodes-$port.conf
cluster-node-timeout 5000
appendonly yes
dir /var/lib/redis/cluster/$port/
EOF
done

# 启动集群节点
for port in 7000 7001 7002 7003 7004 7005; do
    redis-server /etc/redis/cluster/$port/redis.conf &
done

# 创建集群
redis-cli --cluster create \
  127.0.0.1:7000 127.0.0.1:7001 127.0.0.1:7002 \
  127.0.0.1:7003 127.0.0.1:7004 127.0.0.1:7005 \
  --cluster-replicas 1
```

## 📊 监控配置

### Prometheus监控

**Prometheus配置** (`prometheus.yml`):
```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "cota_rules.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093

scrape_configs:
  # COTA服务监控
  - job_name: 'cota'
    static_configs:
      - targets: ['localhost:5005', 'localhost:5006', 'localhost:5007']
    metrics_path: /metrics
    scrape_interval: 15s
    
  # 系统监控
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
    
  # Nginx监控
  - job_name: 'nginx'
    static_configs:
      - targets: ['localhost:9113']
    
  # PostgreSQL监控
  - job_name: 'postgres'
    static_configs:
      - targets: ['localhost:9187']
    
  # Redis监控
  - job_name: 'redis'
    static_configs:
      - targets: ['localhost:9121']
```

**告警规则** (`cota_rules.yml`):
```yaml
groups:
  - name: cota_alerts
    rules:
      # 服务可用性告警
      - alert: CotaServiceDown
        expr: up{job="cota"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "COTA服务不可用"
          description: "实例 {{ $labels.instance }} 已经停止响应超过1分钟"
      
      # 响应时间告警
      - alert: HighResponseTime
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "响应时间过高"
          description: "95%的请求响应时间超过2秒"
      
      # 错误率告警
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "错误率过高"
          description: "5xx错误率超过5%"
      
      # 内存使用告警
      - alert: HighMemoryUsage
        expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "内存使用率过高"
          description: "内存使用率超过90%"
```

### Grafana仪表板

**COTA监控仪表板配置**：
```json
{
  "dashboard": {
    "title": "COTA服务监控",
    "panels": [
      {
        "title": "QPS",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(http_requests_total[5m])",
            "legendFormat": "{{instance}}"
          }
        ]
      },
      {
        "title": "响应时间",
        "type": "graph", 
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))",
            "legendFormat": "95th percentile"
          },
          {
            "expr": "histogram_quantile(0.50, rate(http_request_duration_seconds_bucket[5m]))",
            "legendFormat": "50th percentile"
          }
        ]
      },
      {
        "title": "错误率",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(http_requests_total{status=~\"5..\"}[5m]) / rate(http_requests_total[5m])",
            "legendFormat": "5xx错误率"
          }
        ]
      }
    ]
  }
}
```

## 📝 日志配置

### 结构化日志配置

**日志配置文件** (`logging.yml`):
```yaml
version: 1
disable_existing_loggers: false

formatters:
  standard:
    format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
  detailed:
    format: "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s"
  json:
    format: "%(asctime)s"
    class: pythonjsonlogger.jsonlogger.JsonFormatter

handlers:
  console:
    class: logging.StreamHandler
    level: INFO
    formatter: standard
    stream: ext://sys.stdout
    
  file:
    class: logging.handlers.RotatingFileHandler
    level: INFO
    formatter: detailed
    filename: /var/log/cota/cota.log
    maxBytes: 10485760  # 10MB
    backupCount: 5
    
  json_file:
    class: logging.handlers.TimedRotatingFileHandler
    level: INFO
    formatter: json
    filename: /var/log/cota/cota.json
    when: midnight
    interval: 1
    backupCount: 30

loggers:
  cota:
    level: INFO
    handlers: [console, file, json_file]
    propagate: false
    
  cota.processor:
    level: DEBUG
    handlers: [file]
    propagate: false
    
  cota.llm:
    level: WARNING
    handlers: [file]
    propagate: false

root:
  level: INFO
  handlers: [console]
```

### ELK Stack集成

**Filebeat配置** (`filebeat.yml`):
```yaml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/cota/*.log
    fields:
      service: cota
      environment: production
    fields_under_root: true
    
  - type: log
    enabled: true
    paths:
      - /var/log/cota/*.json
    json.keys_under_root: true
    json.add_error_key: true

output.logstash:
  hosts: ["logstash:5044"]

processors:
  - add_host_metadata:
      when.not.contains.tags: forwarded
```

## 🔄 环境管理

### 多环境配置

**开发环境** (`development.env`):
```bash
# 开发环境配置
COTA_ENV=development
COTA_DEBUG=true
COTA_LOG_LEVEL=DEBUG

# 服务配置
COTA_HOST=localhost
COTA_PORT=5005
COTA_WORKERS=1

# 数据库配置（本地）
DATABASE_URL=sqlite:///./dev.db
REDIS_URL=redis://localhost:6379/1

# LLM配置（测试密钥）
OPENAI_API_KEY=sk-test-key
OPENAI_BASE_URL=https://api.openai.com/v1

# 安全配置（宽松）
CORS_ORIGINS=*
RATE_LIMIT_ENABLED=false
```

**生产环境** (`production.env`):
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
DATABASE_URL=postgresql://cota_user:${DB_PASSWORD}@localhost/cota_production
REDIS_URL=redis://localhost:6379/0

# LLM配置
OPENAI_API_KEY=${OPENAI_API_KEY}
OPENAI_BASE_URL=https://api.openai.com/v1

# 安全配置
CORS_ORIGINS=https://yourdomain.com,https://api.yourdomain.com
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# SSL配置
SSL_CERT_PATH=/etc/cota/ssl/certs/fullchain.pem
SSL_KEY_PATH=/etc/cota/ssl/private/privkey.pem

# 监控配置
PROMETHEUS_ENABLED=true
METRICS_PORT=9090
```

### 配置验证脚本

**配置验证脚本** (`validate_config.sh`):
```bash
#!/bin/bash
set -e

CONFIG_DIR="${1:-/opt/cota/config}"
ENV_FILE="${2:-production.env}"

echo "验证COTA配置: $CONFIG_DIR"
echo "环境文件: $ENV_FILE"

# 检查必需的配置文件
required_files=(
    "agent.yml"
    "endpoints.yml"
    "$ENV_FILE"
)

for file in "${required_files[@]}"; do
    if [ ! -f "$CONFIG_DIR/$file" ]; then
        echo "ERROR: 缺少配置文件: $file"
        exit 1
    fi
done

# 验证环境变量
source "$CONFIG_DIR/$ENV_FILE"

required_vars=(
    "DATABASE_URL"
    "OPENAI_API_KEY"
    "COTA_HOST"
    "COTA_PORT"
)

for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "ERROR: 缺少环境变量: $var"
        exit 1
    fi
done

# 验证SSL证书（如果启用）
if [ "$SSL_CERT_PATH" ] && [ "$SSL_KEY_PATH" ]; then
    if ! openssl x509 -in "$SSL_CERT_PATH" -noout -text > /dev/null 2>&1; then
        echo "ERROR: SSL证书无效: $SSL_CERT_PATH"
        exit 1
    fi
    
    if ! openssl rsa -in "$SSL_KEY_PATH" -check -noout > /dev/null 2>&1; then
        echo "ERROR: SSL私钥无效: $SSL_KEY_PATH"
        exit 1
    fi
fi

# 测试数据库连接
echo "测试数据库连接..."
if ! python3 -c "
import os
from sqlalchemy import create_engine
engine = create_engine('$DATABASE_URL')
with engine.connect() as conn:
    result = conn.execute('SELECT 1')
    print('数据库连接成功')
"; then
    echo "ERROR: 数据库连接失败"
    exit 1
fi

# 测试Redis连接
echo "测试Redis连接..."
if ! python3 -c "
import redis
r = redis.from_url('$REDIS_URL')
r.ping()
print('Redis连接成功')
"; then
    echo "ERROR: Redis连接失败"
    exit 1
fi

echo "✓ 配置验证通过"
```

## 🚀 自动化部署

### CI/CD配置

**GitHub Actions部署** (`.github/workflows/deploy.yml`):
```yaml
name: Deploy COTA

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v3
      with:
        python-version: '3.10'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    - name: Run tests
      run: |
        python -m pytest
        
  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Deploy to production
      uses: appleboy/ssh-action@v0.1.5
      with:
        host: ${{ secrets.HOST }}
        username: ${{ secrets.USERNAME }}
        key: ${{ secrets.SSH_KEY }}
        script: |
          cd /opt/cota
          git pull origin main
          ./scripts/deploy.sh production
```

### 配置管理最佳实践

1. **环境分离**: 严格区分开发、测试、生产环境配置
2. **密钥管理**: 使用环境变量或密钥管理系统
3. **配置验证**: 部署前验证所有配置的正确性
4. **版本控制**: 配置文件纳入版本控制，敏感信息除外
5. **自动化**: 使用脚本自动化配置部署和验证过程

通过合理的配置管理，COTA可以在各种环境中稳定、安全、高效地运行。
