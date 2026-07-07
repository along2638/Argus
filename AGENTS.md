# AGENTS.md

## Project

Argus — 智能监控告警系统。RTSP/RTMP 流 → YOLOv11 ONNX 检测 → Redis 去重 → MySQL + MinIO。

## Quick Commands

```bash
# Install
uv pip install -e ".[dev]"

# Run API server (dev mode)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Run ARQ worker (dev: auto-started in main.py; production: separate container)
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

# Docker (one command for full stack: API + worker + Redis + MySQL + MinIO)
docker compose up -d
docker compose logs -f
docker compose down
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
- **3 ONNX models**: general (yolo11l.onnx), fire_smoke, helmet. Each has independent CLASS_MAPPING and confidence threshold in `app/config.py`.
- **3 separate confidence thresholds**: general=0.3, fire_smoke=0.01, helmet=0.25 — do not assume one global threshold.
- **Singleton pattern**: `detector`, `stream_manager`, `alarm_dedup`, `db_service`, `minio_service` are global singletons.
- **CUDA env setup**: `main.py` sets CUDA PATH before `import onnxruntime` — required for GPU. Import order matters.
- **Dual-frame slicing**: 1FPS fixed sampling + scene change detection (threshold 27.0).
- **No foreign keys**: All tables use plain BigInteger for references, cascade handled in business code.
- **JWT blacklisting**: Logout stores token in Redis key `jwt:blacklist:{token}` with TTL matching remaining token validity.
- **ONNX GPU fallback**: CUDA errors suppressed via ONNXRUNTIME_LOG_LEVEL=3, falls back to CPU automatically.
- **Annotation tool API**: Labeling endpoints (`/api/annotations/*`) are defined directly in `app/main.py`, not in a separate router.
- **Two DB layers**: `app/db.py` is the SQLAlchemy async engine (primary). `app/services/database.py` is a legacy aiomysql pool layer used only for raw alarm inserts. New code should use `app/db.py` + ORM.
- **Alarm escalation**: Same alarm type fires N times within 5min window → severity upgrades (normal → important at 3, → critical at 5).
- **Email notification**: SMTP alarm emails via `app/core/email_notifier.py`, config loaded from `SystemConfig` DB table at startup.
- **Stream auto-restore**: On startup, `main.py` recovers streams that were `"running"` in `stream_config` table before last shutdown.
- **Schedule checker**: Background task auto-starts/stops streams based on cron expressions in `StreamConfig.schedule`.
- **Rate limiting**: Redis-based rate limiter used on login/register endpoints. Key format: `ratelimit:{func_name}:{client_ip}`.
- **Stream health recording**: Background task (`health_recorder.py`) periodically snapshots stream health status.
- **Graceful shutdown cascade**: cancel worker → stop all streams → close ARQ pool → close Redis → close MinIO → close detector → close DB pool.
- **CSRF double-submit cookie**: `csrf.py` middleware; state-changing requests need `X-CSRF-Token` header matching `csrf_token` cookie (exempt for Bearer-only API calls).
- **WebSocket alarm push**: `/ws/alarms?token=xxx` broadcasts real-time alarm events to connected clients.
- **Prometheus metrics**: `/metrics` endpoint exposes active streams, queue depth, GPU status.

## Configuration

All config via `.env` (see `.env.example`):

- **MYSQL_DSN**: MySQL connection string. Password special chars: `#` → `%23`, `$` → `%24`
- **JWT_SECRET**: JWT signing secret (default warns at startup, change in production!)
- **CONFIDENCE_THRESHOLD**: 0.3 (general), 0.01 (fire_smoke), 0.25 (helmet no-helmet阈值), 0.40 (helmet 确认阈值)
- **ALARM_CLASSES**: person, animal classes, fire, smoke, no-helmet
- **ALARM_ESCALATION**: window=300s, important=3 hits, critical=5 hits
- **Models path**: ONNX files at paths in `.env`. Missing model = startup failure.
- **Alembic DSN escaping**: `alembic/env.py` doubles `%` → `%%` for configparser compatibility. If you change MYSQL_DSN, run `alembic upgrade head` to verify.

## Testing

- pytest-asyncio with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed
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
| `app/main.py` | FastAPI entry, middleware, annotation APIs (`/api/annotations/*`), ARQ worker bootstrap, stream auto-restore |
| `app/config.py` | `Settings` singleton, loads `.env`, 3 model CLASS_MAPPINGs, 3 confidence thresholds |
| `app/db.py` | SQLAlchemy async engine + session factory + table init (primary DB layer) |
| `app/models/*.py` | 13 exported ORM models (see `__init__.py`), 15 files total (no foreign keys) |
| `app/api/v1/stream.py` | REST API: /start, /stop, /list, /alarms, /detect, image upload |
| `app/api/v1/auth.py` | Auth API: login, register, logout, user/role management, datasets, training, permissions |
| `app/api/v1/admin.py` | Admin API: operation logs, system config, dashboard stats, CSV export, training records |
| `app/core/stream_processor.py` | StreamProcessor (single stream async task, exponential backoff) + StreamManager (singleton) |
| `app/core/detector.py` | MultiModelDetector, 3 ModelSessions, dedicated inference thread pool |
| `app/core/alarm_dedup.py` | Redis SET NX + TTL dedup; key: `alarm:{stream_id}:{class}:{track_id}` |
| `app/core/alarm_severity.py` | Frequency-based severity escalation (normal → important → critical) |
| `app/core/alarm_broadcaster.py` | WebSocket alarm push singleton |
| `app/core/email_notifier.py` | SMTP alarm email notifications (config from SystemConfig DB table) |
| `app/core/schedule_checker.py` | Cron-based auto-start/stop streams |
| `app/core/rate_limiter.py` | Redis-based rate limiter decorator for endpoints |
| `app/core/csrf.py` | Double-submit cookie CSRF protection middleware |
| `app/core/security_headers.py` | Security headers middleware |
| `app/core/gpu_monitor.py` | GPU memory/availability monitoring |
| `app/core/metrics.py` | Prometheus-compatible metrics endpoint |
| `app/services/database.py` | Legacy aiomysql pool (raw SQL for alarm inserts only) |
| `app/services/auth_service.py` | Auth CRUD, PBKDF2, JWT blacklist (Redis), session management |
| `app/services/worker_tasks.py` | ARQ WorkerSettings + save_alarm task |
| `app/services/operation_log_service.py` | Audit trail writes (async, fire-and-forget) |
| `app/core/auth_decorator.py` | `require_perm(perm)` — permission decorator for endpoints |
| `app/core/batch_analyzer.py` | Batch video analysis — process multiple video files, HTML report |
| `app/models/role_permission.py` | RBAC role→permission mapping (imported in `db.py`, not exported from `models/__init__`) |
| `scripts/init_db.sql` | SQL DDL (reference only, SQLAlchemy auto-creates) |

## Notes

- **CLAUDE.md has stale references**: mentions PostgreSQL/asyncpg in architecture diagrams — this codebase uses MySQL + aiomysql everywhere. Trust `AGENTS.md` and source code over CLAUDE.md.
- **Models in gitignored dirs**: `fire_smoke_data/`, `fire_yolo/`, `fire_dataset/`, `Fire-Detection-v2-1/`, `Fire&smoke-detection-*` are training data, gitignored. `scripts/` contains ad-hoc training/test scripts.
