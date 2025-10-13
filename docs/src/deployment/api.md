# API接口文档

COTA框架提供了一套完整的REST API接口，用于与智能体进行交互、管理对话状态和获取系统信息。

## 📋 API概览

COTA API基于RESTful设计原则，使用JSON格式进行数据交换，支持跨域访问(CORS)。

### 基础信息
- **协议**: HTTP/HTTPS
- **数据格式**: JSON
- **字符编码**: UTF-8
- **跨域支持**: 是
- **认证方式**: 无需认证 (可根据需求扩展)

### 服务器配置
```python
# CORS配置
CORS_AUTOMATIC_OPTIONS = True
CORS_SUPPORTS_CREDENTIALS = True
CORS_EXPOSE_HEADERS = "filename"
```

## 🔧 系统接口

### 获取版本信息

获取COTA框架的版本信息。

```http
GET /version
```

**响应示例**:
```json
{
  "version": "1.0.0"
}
```

**响应状态码**:
- `200 OK`: 成功获取版本信息

**使用示例**:
```bash
curl -X GET http://localhost:5005/version
```

```javascript
// JavaScript示例
fetch('http://localhost:5005/version')
  .then(response => response.json())
  .then(data => console.log('COTA版本:', data.version));
```

## 💬 对话管理接口

### 发送消息

向指定会话发送用户消息，智能体会处理消息并更新对话状态。

```http
POST /add/message/{session_id}/tracker
```

**路径参数**:
| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `session_id` | string | 是 | 会话标识符 |

**请求体参数**:
| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `text` | string | 是 | 用户消息内容 |
| `sender` | string | 否 | 发送者角色，默认为"user" |
| `sender_id` | string | 否 | 发送者ID |
| `meta_data` | object | 否 | 消息元数据 |

**请求示例**:
```json
{
  "text": "你好，请帮我查询今天的天气",
  "sender": "user",
  "sender_id": "user_123",
  "meta_data": {
    "timestamp": "2024-01-01T10:00:00Z",
    "source": "web"
  }
}
```

**响应示例**:
```json
{
  "session_id": "session_456",
  "slots": {
    "city": null,
    "date": "今天"
  },
  "actions": [
    {
      "name": "UserUtter",
      "timestamp": "2024-01-01T10:00:00Z",
      "result": [
        {
          "text": "你好，请帮我查询今天的天气",
          "sender": "user",
          "sender_id": "user_123"
        }
      ]
    },
    {
      "name": "BotUtter",
      "timestamp": "2024-01-01T10:00:01Z",
      "result": [
        {
          "text": "好的，请问您想查询哪个城市的天气？",
          "sender": "bot",
          "sender_id": "bot_assistant"
        }
      ]
    }
  ]
}
```

**响应状态码**:
- `200 OK`: 消息处理成功
- `400 Bad Request`: 请求参数错误
- `500 Internal Server Error`: 服务器内部错误

**使用示例**:
```bash
curl -X POST http://localhost:5005/add/message/session_123/tracker \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你好，请帮我查询今天的天气",
    "sender": "user",
    "sender_id": "user_123"
  }'
```

```python
import requests

url = "http://localhost:5005/add/message/session_123/tracker"
payload = {
    "text": "你好，请帮我查询今天的天气",
    "sender": "user", 
    "sender_id": "user_123"
}

response = requests.post(url, json=payload)
result = response.json()
print("对话状态:", result)
```

### 获取对话状态

获取指定会话的完整对话状态和历史记录。

```http
GET /get/conversations/{conversation_id}/tracker
```

**路径参数**:
| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `conversation_id` | string | 是 | 会话标识符 |

**响应示例**:
```json
{
  "session_id": "session_456",
  "slots": {
    "city": "北京",
    "date": "今天"
  },
  "actions": [
    {
      "name": "UserUtter",
      "timestamp": "2024-01-01T10:00:00Z",
      "result": [
        {
          "text": "查询北京今天的天气",
          "sender": "user",
          "sender_id": "user_123"
        }
      ]
    },
    {
      "name": "Weather",
      "timestamp": "2024-01-01T10:00:01Z", 
      "result": [
        {
          "text": "北京今天晴天，温度25°C，湿度60%",
          "sender": "bot",
          "sender_id": "bot_assistant"
        }
      ]
    }
  ]
}
```

**响应状态码**:
- `200 OK`: 成功获取对话状态
- `404 Not Found`: 会话不存在
- `500 Internal Server Error`: 服务器内部错误

**使用示例**:
```bash
curl -X GET http://localhost:5005/get/conversations/session_123/tracker
```

```javascript
// 获取对话状态
async function getConversationState(conversationId) {
  try {
    const response = await fetch(`/get/conversations/${conversationId}/tracker`);
    const state = await response.json();
    console.log('对话状态:', state);
    return state;
  } catch (error) {
    console.error('获取对话状态失败:', error);
  }
}
```

### 获取最新消息

批量获取多个会话的最新消息内容。

```http
GET /get/latest/utter/conversations?conversation_ids=[id1,id2,...]
```

**查询参数**:
| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `conversation_ids` | array | 是 | 会话ID数组，JSON格式字符串 |

**请求示例**:
```
GET /get/latest/utter/conversations?conversation_ids=["session_123","session_456"]
```

**响应示例**:
```json
{
  "conversations": [
    {
      "text": "北京今天晴天，温度25°C",
      "sender": "bot",
      "sender_id": "bot_assistant",
      "timestamp": "2024-01-01T10:00:01Z",
      "session_id": "session_123"
    },
    {
      "text": "好的，我已经为您预订了酒店",
      "sender": "bot", 
      "sender_id": "bot_assistant",
      "timestamp": "2024-01-01T10:05:00Z",
      "session_id": "session_456"
    }
  ]
}
```

**响应状态码**:
- `200 OK`: 成功获取最新消息
- `400 Bad Request`: 请求参数错误
- `500 Internal Server Error`: 服务器内部错误

**使用示例**:
```bash
curl -X GET "http://localhost:5005/get/latest/utter/conversations?conversation_ids=[\"session_123\",\"session_456\"]"
```

```python
import requests
import json

# 获取多个会话的最新消息
conversation_ids = ["session_123", "session_456"]
url = f"http://localhost:5005/get/latest/utter/conversations"
params = {"conversation_ids": json.dumps(conversation_ids)}

response = requests.get(url, params=params)
result = response.json()
print("最新消息:", result['conversations'])
```

### 获取历史消息

获取指定会话的完整历史消息记录。

```http
GET /get/history/message/conversation/{conversation_id}
```

**路径参数**:
| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `conversation_id` | string | 是 | 会话标识符 |

**响应示例**:
```json
{
  "conversations": [
    {
      "text": "你好",
      "sender": "user",
      "sender_id": "user_123",
      "timestamp": "2024-01-01T09:58:00Z",
      "type": "text"
    },
    {
      "text": "您好！我是COTA智能助手，有什么可以帮您的吗？",
      "sender": "bot",
      "sender_id": "bot_assistant", 
      "timestamp": "2024-01-01T09:58:01Z",
      "type": "text"
    },
    {
      "text": "查询北京今天的天气",
      "sender": "user",
      "sender_id": "user_123",
      "timestamp": "2024-01-01T10:00:00Z", 
      "type": "text"
    },
    {
      "text": "北京今天晴天，温度25°C，湿度60%",
      "sender": "bot",
      "sender_id": "bot_assistant",
      "timestamp": "2024-01-01T10:00:01Z",
      "type": "text"
    }
  ]
}
```

**错误响应**:
```json
{
  "error": "Conversation ID not provided",
  "status": 400
}
```

**响应状态码**:
- `200 OK`: 成功获取历史消息
- `400 Bad Request`: 会话ID未提供
- `404 Not Found`: 会话不存在  
- `500 Internal Server Error`: 服务器内部错误

**使用示例**:
```bash
curl -X GET http://localhost:5005/get/history/message/conversation/session_123
```

```python
import requests

def get_conversation_history(conversation_id):
    """获取会话历史消息"""
    url = f"http://localhost:5005/get/history/message/conversation/{conversation_id}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        messages = data.get('conversations', [])
        
        print(f"会话 {conversation_id} 的历史消息:")
        for msg in messages:
            print(f"[{msg['timestamp']}] {msg['sender']}: {msg['text']}")
            
        return messages
    except requests.exceptions.RequestException as e:
        print(f"获取历史消息失败: {e}")
        return []

# 使用示例
history = get_conversation_history("session_123")
```

## 🔍 数据结构说明

### Message对象
```json
{
  "text": "string",           // 消息内容
  "sender": "string",        // 发送者角色 (user/bot)
  "sender_id": "string",     // 发送者ID
  "receiver": "string",      // 接收者角色 (可选)
  "receiver_id": "string",   // 接收者ID (可选)
  "session_id": "string",    // 会话ID
  "timestamp": "string",     // 时间戳 (ISO格式)
  "type": "string",          // 消息类型 (text/image)
  "metadata": {}             // 元数据对象 (可选)
}
```

### Action对象
```json
{
  "name": "string",          // 动作名称
  "description": "string",   // 动作描述 (可选)
  "timestamp": "string",     // 执行时间戳
  "result": [                // 执行结果数组
    {
      "text": "string",      // 结果文本
      "sender": "string",    // 发送者
      "sender_id": "string", // 发送者ID
      "type": "string"       // 结果类型
    }
  ]
}
```

### DST状态对象
```json
{
  "session_id": "string",    // 会话ID
  "slots": {},               // 槽位信息字典
  "actions": []              // 动作历史数组
}
```

## 🛠️ 错误处理

### 错误响应格式
```json
{
  "error": "错误描述信息",
  "status": 400,
  "details": {
    "field": "具体错误字段",
    "message": "详细错误信息"
  }
}
```

### 常见错误码
| 状态码 | 说明 | 解决方案 |
|--------|------|----------|
| 400 | 请求参数错误 | 检查请求参数格式和必填字段 |
| 404 | 资源不存在 | 确认会话ID或路径是否正确 |
| 500 | 服务器内部错误 | 检查服务器日志，联系管理员 |

## 📝 使用最佳实践

### 1. 会话管理
```python
import uuid
import requests

class CotaClient:
    def __init__(self, base_url="http://localhost:5005"):
        self.base_url = base_url
        self.session_id = str(uuid.uuid4())
    
    def send_message(self, text, sender_id="user"):
        """发送消息到智能体"""
        url = f"{self.base_url}/add/message/{self.session_id}/tracker"
        payload = {
            "text": text,
            "sender": "user",
            "sender_id": sender_id
        }
        
        response = requests.post(url, json=payload)
        return response.json()
    
    def get_history(self):
        """获取对话历史"""
        url = f"{self.base_url}/get/history/message/conversation/{self.session_id}"
        response = requests.get(url)
        return response.json()

# 使用示例
client = CotaClient()
result = client.send_message("你好")
print("智能体回复:", result)
```

### 2. 错误处理
```python
def safe_api_call(func):
    """API调用装饰器，统一错误处理"""
    def wrapper(*args, **kwargs):
        try:
            response = func(*args, **kwargs)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"API错误: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"网络错误: {e}")
            return None
    return wrapper

@safe_api_call
def send_message_safe(session_id, text):
    return requests.post(
        f"http://localhost:5005/add/message/{session_id}/tracker",
        json={"text": text}
    )
```

### 3. 批量操作
```python
async def batch_get_latest_messages(conversation_ids):
    """批量获取最新消息"""
    import aiohttp
    import json
    
    async with aiohttp.ClientSession() as session:
        url = "http://localhost:5005/get/latest/utter/conversations"
        params = {"conversation_ids": json.dumps(conversation_ids)}
        
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('conversations', [])
            else:
                print(f"批量获取失败: {response.status}")
                return []
```

## 📊 性能考虑

### 请求限制
- 建议单次请求消息长度不超过10KB
- 批量查询会话ID不超过100个
- 并发请求控制在合理范围内

### 缓存策略
- 对话状态会自动缓存
- 历史消息支持增量获取
- 建议客户端实现本地缓存

### 监控指标
- 响应时间监控
- 错误率统计
- 并发连接数跟踪

这套API接口为COTA提供了完整的程序化交互能力，支持各种客户端和集成场景。
