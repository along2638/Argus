# AGENTS.md

## Project

Argus — 智能监控告警系统。RTSP/RTMP 流 → YOLOv11 ONNX 检测 → Redis 去重 → MySQL + MinIO。

## Quick Commands

```bash
# Install
uv pip install -e ".[dev]"

# Run API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Run ARQ worker
arq app.services.worker_tasks.WorkerSettings

# Tests
pytest tests/ -v --cov=app

# Lint & format
ruff check app/
ruff format app/

# Type check
mypy app/

# Database migration
alembic upgrade head              # apply all migrations
alembic revision --autogenerate -m "describe_change"  # generate new migration
alembic history                   # view migration history
alembic downgrade -1              # rollback one step
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web | FastAPI (async) |
| ORM | SQLAlchemy 2.0 + aiomysql |
| DB | MySQL 5.7+ |
| Detection | YOLOv11 ONNX (GPU/CPU) |
| Stream | PyAV (RTSP/RTMP) |
| Tracking | ByteTrack (supervision) |
| Queue | ARQ + Redis |
| Storage | MinIO |
| Auth | PBKDF2-SHA256 + JWT |
| Migration | Alembic |

## Architecture Gotchas

- **ARQ worker runs in-background thread**: `main.py` auto-starts the worker in a `ThreadPoolExecutor`. For production (Docker), worker runs as separate container.
- **3 ONNX models**: general (yolo11l.onnx), fire_smoke, helmet. Each has independent CLASS_MAPPING in `app/config.py`.
- **Singleton pattern**: `detector`, `stream_manager`, `alarm_dedup`, `db_service`, `minio_service` are global singletons.
- **CUDA env setup**: `main.py` sets CUDA PATH before `import onnxruntime` — required for GPU.
- **Dual-frame slicing**: 1FPS fixed sampling + scene change detection (threshold 27.0).
- **No foreign keys**: All tables use plain BigInteger for references, cascade handled in business code.
- **JWT blacklisting**: Logout stores token in Redis with TTL matching token expiry.
- **ONNX GPU fallback**: CUDA errors suppressed via ONNXRUNTIME_LOG_LEVEL=3, falls back to CPU automatically.

## Configuration

All config via `.env` (see `.env.example`):

- **MYSQL_DSN**: MySQL connection string. Password special chars: `#` → `%23`, `$` → `%24`
- **JWT_SECRET**: JWT signing secret (change in production!)
- **CONFIDENCE_THRESHOLD**: 0.3 (general), 0.01 (fire_smoke)
- **ALARM_CLASSES**: person, animal classes, fire, smoke, no-helmet
- **Models path**: ONNX files at paths in `.env`. Missing model = startup failure.

## Testing

- pytest-asyncio with `asyncio_mode = "auto"`
- No global `conftest.py` — fixtures per test file
- Heavy use of `unittest.mock` for ONNX/Redis/MySQL/MinIO
- Reset singletons in fixtures: `MultiModelDetector._instance = None`

## Code Style

- Python 3.11+, Ruff (line-length=120, target py311)
- Ruff rules: E/F/I/N/W/UP, ignore E501
- Structured logging: `structlog`
- Type hints required: pydantic + standard typing

## Key Files

| File | Role |
|------|------|
| `app/main.py` | FastAPI entry, middleware, annotation APIs |
| `app/config.py` | `Settings` singleton, loads `.env` |
| `app/db.py` | SQLAlchemy engine, session factory, Base |
| `app/models/*.py` | 11 ORM models (no foreign keys) |
| `app/api/v1/stream.py` | REST API: /start, /stop, /list, /alarms, /detect |
| `app/api/v1/auth.py` | Auth API: login, register, logout, user management |
| `app/core/stream_processor.py` | StreamProcessor + StreamManager |
| `app/core/detector.py` | MultiModelDetector, 3 ModelSessions |
| `app/core/alarm_dedup.py` | Redis SET NX + TTL dedup |
| `app/services/database.py` | DatabaseService (aiomysql pool + ORM) |
| `app/services/auth_service.py` | Auth CRUD, PBKDF2, session management |
| `app/services/worker_tasks.py` | ARQ WorkerSettings + save_alarm |
| `scripts/init_db.sql` | SQL DDL (reference only, SQLAlchemy auto-creates) |
