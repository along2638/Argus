# AGENTS.md

## Project

Argus — real-time video monitoring alarm system. RTSP/RTMP streams → YOLOv11 ONNX detection → Redis dedup → PostgreSQL + MinIO.

## Quick Commands

```bash
# Install (prefer uv)
uv pip install -e ".[dev]"

# Run API server (dev mode with auto-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Run ARQ worker (SEPARATE terminal required)
arq app.services.worker_tasks.WorkerSettings

# Tests
pytest tests/ -v --cov=app

# Lint & format
ruff check app/
ruff format app/

# Type check
mypy app/
```

## Architecture Gotchas

- **ARQ worker runs in-background thread**: `main.py` auto-starts the worker in a `ThreadPoolExecutor` with its own event loop. No separate terminal needed for dev. For production, run `arq` separately for resource isolation.
- **3 ONNX models**: general (yolo11l.onnx), fire_smoke, helmet. Each has independent CLASS_MAPPING in `app/config.py`. Models stored in `models/onnx/`.
- **Singleton pattern**: `detector`, `stream_manager`, `alarm_dedup`, `db_service`, `minio_service` are all global singletons. Reset `_instance = None` in test fixtures.
- **ONNX provider auto-fallback**: CUDA → CPU. Check `session.get_providers()` after init, not just available providers.
- **Dual-frame slicing**: 1FPS fixed sampling + scene change detection (frame diff). Threshold hardcoded at 27.0 in `stream_processor.py`.

## Configuration

All config via `.env` (see `.env.example`). Critical gotchas:

- **Password encoding**: `@` in PG_DSN/REDIS_URL must be `%40` (URL-encoded)
- **CONFIDENCE_THRESHOLD**: `.env` overrides `config.py` default. Current `.env` value: 0.3. Animal detection is sensitive to this.
- **ALARM_CLASSES**: Controls which detections trigger alarms. Default includes person, animal classes, fire, smoke, no-helmet.
- **Models path**: ONNX files must exist at paths specified in `.env`. Missing model = startup failure.

## Testing

- pytest-asyncio with `asyncio_mode = "auto"` — no need for `@pytest.mark.asyncio` decorator
- No global `conftest.py` — fixtures defined per test file
- Heavy use of `unittest.mock` (MagicMock, AsyncMock, patch) for ONNX/Redis/PG/MinIO
- Singletons leak between tests — always reset in fixtures:
  ```python
  from app.core.detector import MultiModelDetector
  MultiModelDetector._instance = None
  ```

## Code Style

- Python 3.11+, Ruff (line-length=120, target py311)
- Ruff rules: E/F/I/N/W/UP, ignore E501
- Structured logging: `structlog` (console/JSON auto-switch)
- Type hints required: pydantic models + standard typing

## Key Files

| File | Role |
|------|------|
| `app/main.py` | FastAPI entry, lifespan manages startup/shutdown cascade |
| `app/config.py` | `Settings` singleton, loads `.env` |
| `app/api/v1/stream.py` | REST API: /start, /stop, /list, /alarms |
| `app/core/stream_processor.py` | StreamProcessor + StreamManager (exponential backoff reconnect) |
| `app/core/detector.py` | MultiModelDetector, 3 ModelSessions, preprocess/postprocess |
| `app/core/alarm_dedup.py` | Redis SET NX + TTL dedup (30s cooldown) |
| `app/services/worker_tasks.py` | ARQ WorkerSettings + save_alarm task |
