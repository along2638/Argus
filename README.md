# YOLO Stream Alarm

轻量级监控流实时切片与多目标告警系统

## 功能特性

- 🎥 **实时流处理**: 支持 RTSP/RTMP 监控流接入
- 🔍 **智能检测**: 基于 YOLOv11 的多目标检测
- 📊 **双策略切片**: 场景变化检测 + 固定帧率采样
- 🎯 **目标跟踪**: ByteTrack 实时目标跟踪与去重
- 🔔 **告警类型**:
  - 安全帽佩戴检测 (helmet / no-helmet)
  - 火灾烟雾检测 (fire / smoke)
  - 入侵检测 (intrusion / person)
- 💾 **异步存储**: MinIO 图片存储 + PostgreSQL 元数据
- 🚀 **高性能**: ONNX Runtime 推理加速，支持 CPU/GPU

## 技术栈

| 模块 | 技术 |
|:---|:---|
| 核心检测 | YOLOv11l (ONNX FP32, 通用) + YOLOv8n (FP16, 火灾烟雾/安全帽) |
| 智能切片 | PySceneDetect + 固定帧率采样 |
| 时序后处理 | supervision (ByteTrack + ROI) |
| 推理加速 | ONNX Runtime |
| 流媒体拉流 | PyAV |
| 业务服务 | FastAPI (全异步) |
| 任务队列 | ARQ (基于 Redis) |
| 对象存储 | MinIO |
| 数据库 | PostgreSQL + asyncpg |
| 配置管理 | pydantic-settings + .env |
| 容器化 | Docker Compose |

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repository-url>
cd yolo-stream-alarm

# 复制环境配置
cp .env.example .env

# 编辑 .env 文件，配置数据库连接信息
```

### 2. 安装依赖

```bash
# 使用 pip
pip install -e .

# 或使用 uv (推荐)
uv pip install -e .
```

### 3. 模型准备

将训练好的 YOLOv11n 模型转换为 ONNX FP16 格式：

```bash
python scripts/export_onnx.py \
    --model path/to/yolov11n.pt \
    --output models/yolov11n_fp16.onnx \
    --verify
```

### 4. 数据库初始化

```bash
# 使用提供的 SQL 脚本
psql -h <host> -p <port> -U <user> -d <database> -f scripts/init_db.sql
```

### 5. 启动服务

#### 方式一：直接运行

```bash
# 启动 API 服务（ARQ Worker 自动在后台启动）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 方式二：Docker Compose (推荐)

```bash
# 一键启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down
```

## API 文档

启动服务后访问：

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 接口列表

#### 启动流处理

```http
POST /api/v1/stream/start
Content-Type: application/json

{
    "stream_url": "rtsp://username:password@camera-ip:port/stream",
    "stream_id": "camera-001"
}
```

#### 停止流处理

```http
POST /api/v1/stream/stop
Content-Type: application/json

{
    "stream_id": "camera-001"
}
```

#### 健康检查

```http
GET /health

Response:
{
    "status": "ok",
    "active_streams": 2,
    "queue_depth": 0,
    "gpu_available": true
}
```

#### 流列表

```http
GET /api/v1/stream/list

Response:
{
    "active_streams": 2,
    "max_streams": 10,
    "streams": ["camera-001", "camera-002"]
}
```

## 环境变量说明

| 变量名 | 说明 | 默认值 |
|:---|:---|:---|
| MINIO_ENDPOINT | MinIO 服务地址 | your_minio_endpoint:9000 |
| MINIO_BUCKET | 存储桶名称 | your_bucket_name |
| MINIO_ACCESS_KEY | MinIO 访问密钥 | your_access_key |
| MINIO_SECRET_KEY | MinIO 密钥 | your_secret_key |
| PG_DSN | PostgreSQL 连接串 | - |
| REDIS_URL | Redis 连接地址 | - |
| YOLO_ONNX_PATH | 通用检测模型路径 | ./models/onnx/yolo11l.onnx |
| APP_HOST | 监听地址 | 0.0.0.0 |
| APP_PORT | 监听端口 | 8000 |
| MAX_CONCURRENT_STREAMS | 最大并发流数 | 10 |
| CONFIDENCE_THRESHOLD | 置信度阈值 | 0.3 |
| ALARM_COOLDOWN_TTL | 告警冷却时间(秒) | 30 |

## 项目结构

```
yolo-stream-alarm/
├── .env.example                # 环境变量模板
├── .gitignore
├── docker-compose.yml          # Docker 编排
├── Dockerfile
├── pyproject.toml              # 依赖管理
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理
│   ├── api/
│   │   └── v1/
│   │       └── stream.py       # 流处理 API
│   ├── core/
│   │   ├── stream_processor.py # 流处理核心
│   │   ├── detector.py         # YOLO 检测器
│   │   └── alarm_dedup.py      # 告警去重
│   ├── services/
│   │   ├── database.py         # 数据库服务
│   │   ├── minio_client.py     # MinIO 客户端
│   │   └── worker_tasks.py     # ARQ 任务
│   └── utils/
│       └── logger.py           # 日志配置
├── models/
│   ├── onnx/                   # ONNX 推理模型
│   │   ├── yolo11l.onnx        # 通用检测模型 (FP32)
│   │   ├── fire_smoke_v2.onnx   # 火灾烟雾模型 (FP16)
│   │   └── helmet_fp16.onnx    # 安全帽模型 (FP16)
│   └── pt/                     # PyTorch 训练模型
│       ├── yolo11l.pt
│       └── yolo11n.pt
├── scripts/
│   ├── export_onnx.py          # 模型导出脚本
│   └── init_db.sql             # 数据库初始化
└── tests/                      # 测试文件
```

## 开发指南

### 运行测试

```bash
pytest tests/ -v --cov=app
```

### 代码检查

```bash
ruff check app/
ruff format app/
```

### 类型检查

```bash
mypy app/
```

## 部署建议

1. **生产环境**: 使用 Docker Compose 部署，确保所有服务健康检查配置正确
2. **GPU 支持**: 安装 NVIDIA Container Toolkit 以支持 GPU 推理
3. **日志收集**: 配置日志聚合工具 (如 ELK, Loki) 收集 JSON 格式日志
4. **监控**: 集成 Prometheus + Grafana 监控系统指标
5. **备份**: 定期备份 PostgreSQL 和 MinIO 数据

## 许可证

MIT License
