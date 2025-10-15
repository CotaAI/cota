# 故障排除

本文档收录了COTA部署和运行中常见的问题及其解决方案，帮助你快速定位和解决问题。

## 🔍 问题分类

```mermaid
graph TD
    Problems[常见问题] --> Installation[安装问题]
    Problems --> Configuration[配置问题]
    Problems --> Runtime[运行时问题]
    Problems --> Performance[性能问题]
    Problems --> Network[网络问题]
    
    Installation --> Dependencies[依赖问题]
    Installation --> Environment[环境问题]
    
    Configuration --> YAMLSyntax[YAML语法错误]
    Configuration --> MissingKeys[缺失配置项]
    Configuration --> InvalidValues[无效配置值]
    
    Runtime --> ServiceStart[服务启动失败]
    Runtime --> ConnectionError[连接错误]
    Runtime --> LLMError[LLM调用失败]
    
    Performance --> SlowResponse[响应缓慢]
    Performance --> HighMemory[内存使用过高]
    Performance --> DatabaseSlow[数据库缓慢]
    
    Network --> PortConflict[端口冲突]
    Network --> SSLError[SSL错误]
    Network --> ProxyError[代理错误]
```

## 🛠️ 安装问题

### Poetry安装失败

**问题症状**：
```bash
curl -sSL https://install.python-poetry.org | python3 -
# 安装失败或命令不存在
```

**解决方案**：

1. **手动安装Poetry**：
```bash
# 下载安装脚本
wget https://install.python-poetry.org -O install-poetry.py
python3 install-poetry.py

# 添加到PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

2. **使用pip安装**：
```bash
pip install --user poetry
```

3. **验证安装**：
```bash
poetry --version
which poetry
```

### 依赖安装问题

**问题症状**：
```bash
poetry install
# ModuleNotFoundError或版本冲突
```

**解决方案**：

1. **清理缓存**：
```bash
poetry cache clear pypi --all
poetry cache clear _default_cache --all
```

2. **重新安装**：
```bash
rm poetry.lock
poetry install
```

3. **指定Python版本**：
```bash
poetry env use python3.10
poetry install
```

### Python版本不兼容

**问题症状**：
```bash
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

**解决方案**：

1. **检查Python版本**：
```bash
python --version
# 需要Python 3.8+
```

2. **安装正确版本**：
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3.10 python3.10-venv python3.10-dev

# CentOS/RHEL
sudo dnf install python3.10 python3.10-devel

# macOS
brew install python@3.10
```

3. **创建虚拟环境**：
```bash
python3.10 -m venv cota_env
source cota_env/bin/activate
```

## ⚙️ 配置问题

### YAML语法错误

**问题症状**：
```bash
yaml.scanner.ScannerError: mapping values are not allowed here
```

**解决方案**：

1. **验证YAML语法**：
```bash
# 安装yamllint
pip install yamllint

# 检查语法
yamllint agent.yml
yamllint endpoints.yml
```

2. **常见语法错误修正**：
```yaml
# 错误：缺少空格
key:value

# 正确：冒号后加空格
key: value

# 错误：缩进不一致
items:
  - name: item1
    value: 1
   - name: item2  # 缩进错误
     value: 2

# 正确：保持一致缩进
items:
  - name: item1
    value: 1
  - name: item2
    value: 2
```

3. **使用YAML验证工具**：
```python
import yaml

def validate_yaml(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            yaml.safe_load(f)
        print(f"✓ {file_path} 语法正确")
    except yaml.YAMLError as e:
        print(f"✗ {file_path} 语法错误: {e}")

validate_yaml('agent.yml')
validate_yaml('endpoints.yml')
```

### 环境变量未设置

**问题症状**：
```bash
KeyError: 'OPENAI_API_KEY'
ConfigurationError: Missing required environment variable
```

**解决方案**：

1. **检查环境变量**：
```bash
# 检查变量是否设置
echo $OPENAI_API_KEY
env | grep COTA

# 检查所有相关变量
printenv | grep -E "(OPENAI|COTA|DATABASE|REDIS)"
```

2. **设置环境变量**：
```bash
# 临时设置
export OPENAI_API_KEY="your_api_key_here"
export DATABASE_URL="postgresql://user:pass@localhost/db"

# 永久设置（添加到 ~/.bashrc）
echo 'export OPENAI_API_KEY="your_api_key_here"' >> ~/.bashrc
source ~/.bashrc
```

3. **使用.env文件**：
```bash
# 创建.env文件
cat > .env << EOF
OPENAI_API_KEY=your_api_key_here
DATABASE_URL=postgresql://user:pass@localhost/db
REDIS_URL=redis://localhost:6379/0
EOF

# 加载环境变量
set -a && source .env && set +a
```

### LLM配置错误

**问题症状**：
```bash
OpenAIError: Invalid API key
AuthenticationError: Incorrect API key provided
```

**解决方案**：

1. **验证API密钥**：
```bash
# 测试OpenAI API
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# 测试其他LLM API
curl -X POST https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"Hello"}]}'
```

2. **检查endpoints.yml配置**：
```yaml
llm:
  gpt-3.5-turbo:
    type: "openai"
    api_key: "${OPENAI_API_KEY}"  # 确保使用环境变量
    base_url: "https://api.openai.com/v1"  # 检查URL是否正确
    model: "gpt-3.5-turbo"
    max_tokens: 2000
    temperature: 0.7
```

3. **测试LLM连接**：
```python
import asyncio
from cota.llm import LLM

async def test_llm():
    config = {
        "type": "openai",
        "api_key": "your_api_key",
        "model": "gpt-3.5-turbo"
    }
    
    llm = LLM(config)
    try:
        result = await llm.generate_chat([
            {"role": "user", "content": "Hello"}
        ])
        print("✓ LLM连接成功:", result["content"])
    except Exception as e:
        print("✗ LLM连接失败:", e)

asyncio.run(test_llm())
```

## 🚀 运行时问题

### 服务启动失败

**问题症状**：
```bash
cota run --config=./bot
# 服务无法启动或立即退出
```

**解决方案**：

1. **检查日志**：
```bash
# 启用详细日志
cota run --config=./bot --debug --log=DEBUG

# 查看系统日志
sudo journalctl -u cota -f

# 查看应用日志
tail -f /var/log/cota/cota.log
```

2. **检查端口占用**：
```bash
# 检查端口是否被占用
netstat -tlnp | grep :5005
lsof -i :5005

# 杀死占用端口的进程
sudo kill -9 $(lsof -t -i:5005)
```

3. **验证配置文件**：
```bash
# 检查配置目录结构
ls -la ./bot/
ls -la ./bot/policy/

# 验证必需文件存在
required_files="agent.yml endpoints.yml policy/data.yml policy/rules.yml"
for file in $required_files; do
    if [ -f "./bot/$file" ]; then
        echo "✓ $file 存在"
    else
        echo "✗ $file 缺失"
    fi
done
```

4. **测试最小配置**：
```bash
# 使用最简配置测试
cota init
cd cota_projects/simplebot
cp endpoints.yml.example endpoints.yml
cota run --config=. --debug
```

### 数据库连接失败

**问题症状**：
```bash
sqlalchemy.exc.OperationalError: could not connect to server
psycopg2.OperationalError: connection to server failed
```

**解决方案**：

1. **检查数据库服务**：
```bash
# PostgreSQL
sudo systemctl status postgresql
sudo systemctl start postgresql

# MySQL
sudo systemctl status mysql
sudo systemctl start mysql

# 检查数据库进程
ps aux | grep postgres
ps aux | grep mysql
```

2. **验证连接参数**：
```bash
# 测试PostgreSQL连接
psql -h localhost -U cota_user -d cota_db

# 测试MySQL连接
mysql -h localhost -u cota_user -p cota_db

# 检查连接字符串格式
echo $DATABASE_URL
```

3. **创建数据库和用户**：
```sql
-- PostgreSQL
CREATE USER cota_user WITH PASSWORD 'password';
CREATE DATABASE cota_db OWNER cota_user;
GRANT ALL PRIVILEGES ON DATABASE cota_db TO cota_user;

-- MySQL
CREATE USER 'cota_user'@'localhost' IDENTIFIED BY 'password';
CREATE DATABASE cota_db;
GRANT ALL PRIVILEGES ON cota_db.* TO 'cota_user'@'localhost';
FLUSH PRIVILEGES;
```

### Redis连接问题

**问题症状**：
```bash
redis.exceptions.ConnectionError: Error connecting to Redis
```

**解决方案**：

1. **检查Redis服务**：
```bash
# 检查Redis状态
sudo systemctl status redis
sudo systemctl start redis

# 测试Redis连接
redis-cli ping
redis-cli -h localhost -p 6379 ping
```

2. **检查Redis配置**：
```bash
# 查看Redis配置
cat /etc/redis/redis.conf | grep -E "(bind|port|requirepass)"

# 检查是否需要密码
redis-cli
AUTH your_password  # 如果设置了密码
```

3. **测试Redis连接**：
```python
import redis

try:
    r = redis.Redis(host='localhost', port=6379, db=0)
    r.ping()
    print("✓ Redis连接成功")
except Exception as e:
    print(f"✗ Redis连接失败: {e}")
```

## 📈 性能问题

### 响应速度慢

**问题症状**：
- API响应时间超过5秒
- 用户界面响应缓慢
- 高并发下性能下降

**解决方案**：

1. **性能分析**：
```bash
# 启用性能分析
cota run --config=./bot --profile

# 使用cProfile分析
python -m cProfile -s cumulative -m cota run --config=./bot
```

2. **数据库优化**：
```sql
-- 创建索引
CREATE INDEX idx_session_id ON conversations(session_id);
CREATE INDEX idx_timestamp ON actions(timestamp);

-- 分析查询性能
EXPLAIN ANALYZE SELECT * FROM conversations WHERE session_id = 'xxx';

-- 优化配置
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
```

3. **缓存优化**：
```python
# Redis缓存配置
CACHE_CONFIG = {
    'default': {
        'BACKEND': 'redis',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'redis_cache.RedisClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            }
        },
        'TIMEOUT': 3600,
    }
}
```

4. **LLM调用优化**：
```python
# 设置合理的超时
llm_config = {
    "timeout": 30,  # 30秒超时
    "max_retries": 3,
    "retry_delay": 1
}

# 使用流式响应
async def stream_response(messages):
    async for chunk in llm.generate_stream(messages):
        yield chunk
```

### 内存使用过高

**问题症状**：
```bash
# 内存使用率持续增长
free -h
top -p $(pgrep cota)
```

**解决方案**：

1. **内存分析**：
```python
import tracemalloc
import psutil
import gc

# 启用内存追踪
tracemalloc.start()

def check_memory():
    process = psutil.Process()
    print(f"内存使用: {process.memory_info().rss / 1024 / 1024:.2f} MB")
    
    current, peak = tracemalloc.get_traced_memory()
    print(f"Python内存: {current / 1024 / 1024:.2f} MB")
    
    # 手动垃圾回收
    gc.collect()
```

2. **优化对话历史管理**：
```python
class DST:
    def __init__(self, max_history=100):
        self.max_history = max_history
        self.actions = deque(maxlen=max_history)  # 限制历史长度
    
    def cleanup_old_sessions(self):
        # 定期清理旧会话
        cutoff_time = datetime.now() - timedelta(hours=24)
        # 删除24小时前的会话
```

3. **连接池配置**：
```python
# 限制数据库连接池大小
DATABASE_CONFIG = {
    "pool_size": 10,
    "max_overflow": 20,
    "pool_recycle": 3600,
    "pool_pre_ping": True
}
```

### 并发问题

**问题症状**：
- 高并发下请求失败
- 数据库连接耗尽
- 资源竞争导致死锁

**解决方案**：

1. **限制并发连接**：
```python
import asyncio

# 使用信号量限制并发
semaphore = asyncio.Semaphore(50)  # 最多50个并发

async def handle_request(request):
    async with semaphore:
        # 处理请求
        return await process_request(request)
```

2. **连接池配置**：
```yaml
# endpoints.yml
data_store:
  type: "sql"
  connection_string: "${DATABASE_URL}"
  pool_size: 20
  max_overflow: 30
  pool_timeout: 30
  pool_recycle: 3600
```

3. **负载均衡**：
```nginx
upstream cota_backend {
    least_conn;  # 最少连接调度
    
    server 127.0.0.1:5005 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:5006 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:5007 max_fails=3 fail_timeout=30s;
}
```

## 🌐 网络问题

### SSL/TLS证书问题

**问题症状**：
```bash
SSL: CERTIFICATE_VERIFY_FAILED
SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
```

**解决方案**：

1. **验证证书**：
```bash
# 检查证书有效期
openssl x509 -in /path/to/cert.pem -text -noout | grep -A 2 Validity

# 检查证书链
openssl s_client -connect yourdomain.com:443 -showcerts

# 验证私钥和证书匹配
openssl x509 -noout -modulus -in cert.pem | openssl md5
openssl rsa -noout -modulus -in private.key | openssl md5
```

2. **更新证书**：
```bash
# Let's Encrypt自动续期
certbot renew --dry-run

# 手动更新
certbot certonly --standalone -d yourdomain.com
```

3. **配置证书链**：
```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;
    
    ssl_certificate /etc/ssl/certs/fullchain.pem;  # 包含完整证书链
    ssl_certificate_key /etc/ssl/private/privkey.pem;
    ssl_trusted_certificate /etc/ssl/certs/chain.pem;
}
```

### WebSocket连接问题

**问题症状**：
- WebSocket连接频繁断开
- 握手失败
- 消息丢失

**解决方案**：

1. **检查代理配置**：
```nginx
location /ws {
    proxy_pass http://cota_backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    
    # 重要：设置长超时
    proxy_read_timeout 86400;
    proxy_send_timeout 86400;
    
    # 禁用缓冲
    proxy_buffering off;
}
```

2. **客户端重连机制**：
```javascript
class WebSocketClient {
    constructor(url) {
        this.url = url;
        this.reconnectInterval = 1000;
        this.maxReconnectInterval = 30000;
        this.reconnectAttempts = 0;
        this.connect();
    }
    
    connect() {
        this.ws = new WebSocket(this.url);
        
        this.ws.onopen = () => {
            console.log('WebSocket连接成功');
            this.reconnectAttempts = 0;
        };
        
        this.ws.onclose = () => {
            this.reconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket错误:', error);
        };
    }
    
    reconnect() {
        setTimeout(() => {
            this.reconnectAttempts++;
            this.connect();
        }, Math.min(this.reconnectInterval * this.reconnectAttempts, this.maxReconnectInterval));
    }
}
```

3. **服务端心跳**：
```python
import asyncio

async def heartbeat(websocket):
    while True:
        try:
            await websocket.ping()
            await asyncio.sleep(30)  # 30秒心跳
        except Exception:
            break
```

## 🔧 调试工具

### 健康检查脚本

```bash
#!/bin/bash
# health_check.sh

set -e

COTA_URL="http://localhost:5005"
TIMEOUT=10

echo "=== COTA健康检查 ==="

# 1. 检查服务进程
echo "检查COTA进程..."
if pgrep -f "cota run" > /dev/null; then
    echo "✓ COTA进程运行中"
else
    echo "✗ COTA进程未运行"
    exit 1
fi

# 2. 检查API响应
echo "检查API响应..."
if curl -f -s --max-time $TIMEOUT "$COTA_URL/version" > /dev/null; then
    VERSION=$(curl -s "$COTA_URL/version" | jq -r '.version' 2>/dev/null || echo "unknown")
    echo "✓ API响应正常，版本: $VERSION"
else
    echo "✗ API无响应"
    exit 1
fi

# 3. 检查数据库连接
echo "检查数据库连接..."
if python3 -c "
import os
from sqlalchemy import create_engine
engine = create_engine(os.environ.get('DATABASE_URL', 'sqlite:///./test.db'))
with engine.connect() as conn:
    conn.execute('SELECT 1')
" 2>/dev/null; then
    echo "✓ 数据库连接正常"
else
    echo "✗ 数据库连接失败"
    exit 1
fi

# 4. 检查Redis连接
echo "检查Redis连接..."
if python3 -c "
import redis
import os
r = redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))
r.ping()
" 2>/dev/null; then
    echo "✓ Redis连接正常"
else
    echo "✗ Redis连接失败"
    exit 1
fi

# 5. 检查磁盘空间
echo "检查磁盘空间..."
DISK_USAGE=$(df /var/log | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 90 ]; then
    echo "✓ 磁盘空间充足 (${DISK_USAGE}%)"
else
    echo "✗ 磁盘空间不足 (${DISK_USAGE}%)"
    exit 1
fi

echo "✓ 所有检查通过"
```

### 日志分析脚本

```bash
#!/bin/bash
# analyze_logs.sh

LOG_FILE="/var/log/cota/cota.log"
HOURS=${1:-1}

echo "=== 最近${HOURS}小时的日志分析 ==="

# 错误统计
echo "错误统计:"
grep -E "ERROR|CRITICAL" "$LOG_FILE" | \
tail -1000 | \
awk -v hours=$HOURS '
BEGIN { cutoff = systime() - (hours * 3600) }
{
    if (match($0, /^([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})/, arr)) {
        cmd = "date -d \"" arr[1] "\" +%s"
        cmd | getline timestamp
        close(cmd)
        if (timestamp >= cutoff) {
            errors[substr($0, match($0, /ERROR|CRITICAL/))]++
        }
    }
}
END {
    for (error in errors) {
        print "  " error ": " errors[error] " 次"
    }
}'

# 响应时间分析
echo -e "\n响应时间分析:"
grep "response_time" "$LOG_FILE" | \
tail -100 | \
awk '{
    if (match($0, /response_time: ([0-9.]+)/, arr)) {
        times[NR] = arr[1]
        sum += arr[1]
        count++
    }
}
END {
    if (count > 0) {
        print "  平均响应时间: " sum/count "s"
        print "  请求数量: " count
    }
}'
```

### 性能监控脚本

```bash
#!/bin/bash
# monitor_performance.sh

DURATION=${1:-60}
INTERVAL=5

echo "监控COTA性能 ${DURATION}秒..."

for ((i=0; i<$((DURATION/INTERVAL)); i++)); do
    echo "=== $(date) ==="
    
    # CPU和内存使用
    PID=$(pgrep -f "cota run" | head -1)
    if [ -n "$PID" ]; then
        ps -p $PID -o pid,ppid,%cpu,%mem,vsz,rss,comm
    fi
    
    # 网络连接数
    echo "活跃连接: $(netstat -an | grep :5005 | grep ESTABLISHED | wc -l)"
    
    # 响应时间测试
    RESPONSE_TIME=$(curl -o /dev/null -s -w '%{time_total}\n' http://localhost:5005/version)
    echo "API响应时间: ${RESPONSE_TIME}s"
    
    sleep $INTERVAL
done
```

## 📞 获取帮助

### 收集调试信息

当遇到问题需要寻求帮助时，请收集以下信息：

```bash
#!/bin/bash
# collect_debug_info.sh

echo "=== COTA调试信息收集 ==="

# 系统信息
echo "系统信息:"
uname -a
cat /etc/os-release 2>/dev/null || cat /etc/redhat-release 2>/dev/null

# Python环境
echo -e "\nPython环境:"
python3 --version
pip --version
poetry --version 2>/dev/null || echo "Poetry未安装"

# COTA版本
echo -e "\nCOTA版本:"
cota --version 2>/dev/null || echo "COTA未安装"

# 进程状态
echo -e "\n进程状态:"
ps aux | grep -E "(cota|python)" | grep -v grep

# 端口监听
echo -e "\n端口监听:"
netstat -tlnp | grep -E ":5005|:6379|:5432"

# 磁盘空间
echo -e "\n磁盘空间:"
df -h

# 内存使用
echo -e "\n内存使用:"
free -h

# 最近日志
echo -e "\n最近错误日志:"
tail -50 /var/log/cota/cota.log 2>/dev/null | grep -E "ERROR|CRITICAL" || echo "无错误日志"
```

### 常用命令参考

```bash
# 快速诊断
cota run --config=./bot --debug --log=DEBUG

# 测试配置
python3 -c "import yaml; yaml.safe_load(open('agent.yml'))"

# 检查端口
netstat -tlnp | grep :5005

# 查看进程
ps aux | grep cota

# 查看日志
journalctl -u cota -f
tail -f /var/log/cota/cota.log

# 重启服务
sudo systemctl restart cota

# 验证SSL
openssl s_client -connect yourdomain.com:443
```

通过这些故障排除方法和工具，你应该能够快速定位和解决COTA部署和运行中遇到的大部分问题。如果问题仍然无法解决，请收集详细的调试信息并向社区或技术支持团队寻求帮助。
