# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Argus (YOLO Stream Alarm) — 实时视频监控告警系统。接收 RTSP/RTMP 摄像头流，通过 YOLOv11n ONNX 模型进行多目标检测（人员入侵、火灾烟雾、安全帽佩戴），检测结果经 Redis 去重后异步写入 PostgreSQL，告警图片存储于 MinIO。

## Common Commands

```bash
# 安装依赖（推荐 uv）
uv pip install -e .
pip install -e .

# 安装开发依赖
uv pip install -e ".[dev]"

# 启动 API 服务（开发模式）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# ARQ Worker 在 main.py 启动时自动在后台线程运行，无需单独终端
# 如需单独运行：arq app.services.worker_tasks.WorkerSettings

# 运行测试
pytest tests/ -v --cov=app

# 代码检查与格式化
ruff check app/
ruff format app/

# 类型检查
mypy app/

# ONNX 模型导出
python scripts/export_onnx.py --model path/to/yolov11n.pt --output models/onnx/yolov11n_fp16.onnx --verify

# 数据库初始化
psql -h <host> -p <port> -U <user> -d <database> -f scripts/init_db.sql

# Docker Compose 一键启动
docker compose up -d
docker compose logs -f
docker compose down
```

## Architecture

```
RTSP/RTMP 流 → StreamProcessor (PyAV 拉流 + 双策略切片: 1FPS采样/场景变化检测)
                    ↓
              MultiModelDetector (3个 ONNX 模型并行推理, 线程池执行避免阻塞事件循环)
                    ↓
              AlarmDeduplicator (Redis SET NX + TTL, 30s 冷却窗口)
                    ↓
              MinIO 图片上传 + ARQ 入队
                    ↓
              ARQ Worker → asyncpg → PostgreSQL (alarm_records)
```

### Key Modules

- `app/main.py` — FastAPI 入口，lifespan 管理所有服务的启动/关闭级联
- `app/config.py` — `Settings` 单例 (pydantic-settings)，从 `.env` 加载所有配置
- `app/api/v1/stream.py` — REST API：`/start`, `/stop`, `/list`, `/alarms`, `/image/{path}`
- `app/core/stream_processor.py` — `StreamProcessor`（单流异步任务，指数退避重连 1s→30s，连续 5 次失败标记离线）+ `StreamManager`（单例，管理所有活跃流，控制并发上限）
- `app/core/detector.py` — `MultiModelDetector` 封装 3 个 `ModelSession`（通用/火灾烟雾/安全帽），preprocess/postprocess 管线
- `app/core/alarm_dedup.py` — Redis 去重，key 格式 `alarm:{stream_id}:{class_name}:{track_id}`
- `app/services/database.py` — asyncpg 连接池 (min=2, max=10)，alarm_records CRUD
- `app/services/minio_client.py` — MinIO 上传，3 次重试，失败返回 None 并记录日志，按日期分区存储
- `app/services/worker_tasks.py` — ARQ WorkerSettings + `save_alarm` 任务 + 入队辅助函数

### Design Patterns

- **单例模式**：`detector`, `stream_manager`, `alarm_dedup`, `db_service`, `minio_service` 均为全局单例
- **全异步架构**：ONNX 推理和 PyAV I/O 通过 `run_in_executor` 卸载到线程池
- **指数退避重连**：1s 到 30s 上限，连续 5 次失败标记流离线
- **优雅关闭级联**：取消 worker → 停止所有流 → 关闭 ARQ pool → 关闭 Redis → 关闭 MinIO → 关闭 detector → 关闭 DB pool

## Configuration

所有配置通过 `.env` 文件管理（参考 `.env.example`）。关键配置项：

- 三个 ONNX 模型路径：`YOLO_ONNX_PATH`（通用）、`FIRE_SMOKE_MODEL_PATH`（火灾烟雾）、`HELMET_MODEL_PATH`（安全帽）
- `ALARM_CLASSES` 控制哪些检测类型触发告警（默认：person, animal classes, fire, smoke, no-helmet）
- `CONFIDENCE_THRESHOLD = 0.3`, `ALARM_COOLDOWN_TTL = 30s`
- 每个模型有独立的 `CLASS_MAPPING`（class ID → 业务告警类型）
- 模型文件存储在 `models/onnx/`（推理用）和 `models/pt/`（训练用）

## Testing Patterns

- pytest + pytest-asyncio（`asyncio_mode = "auto"`，无需显式 `@pytest.mark.asyncio`）
- 大量使用 `unittest.mock`（MagicMock, AsyncMock, patch）模拟外部依赖（ONNX session、Redis、PostgreSQL、MinIO、ARQ pool）
- 单例重置：在 fixture 中通过 `_instance = None` 清除
- 无全局 conftest.py，fixture 定义在各测试文件内

## Code Style

- Python 3.11+，使用 Ruff（line-length=120, target py311）
- Ruff 规则：E/F/I/N/W/UP，忽略 E501（行长度）
- 结构化日志：structlog（控制台/JSON 自动切换）
- 类型注解：pydantic model + 标准 typing
