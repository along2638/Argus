import asyncio
import os
import time
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

# 设置 CUDA 环境变量，必须在 import onnxruntime 之前
import sys
_nvidia_base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
_cuda_dirs = []
for sub in ["cublas/bin", "cudnn/bin", "cufft/bin", "cusolver/bin", "cusparse/bin", "cuda_nvrtc/bin", "cuda_cupti/bin", "nvjitlink/bin"]:
    p = _nvidia_base / sub
    if p.exists():
        _cuda_dirs.append(str(p))
os.environ["PATH"] = ";".join(_cuda_dirs) + ";" + os.environ.get("PATH", "")

# 抑制 ONNX Runtime C++ 层的 CUDA 错误输出
os.environ["ONNXRUNTIME_LOG_LEVEL"] = "3"

import onnxruntime as ort
from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.stream import router as stream_router
from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.config import settings
from app.core.alarm_dedup import alarm_dedup
from app.core.detector import detector
from app.core.stream_processor import stream_manager
from app.services.database import db_service
from app.services.minio_client import minio_service
from app.services.worker_tasks import WorkerSettings, close_arq_pool
from app.services.auth_service import get_current_user, create_default_admin
from app.utils.logger import get_logger, setup_logging, print_status

logger = get_logger(__name__)


# 保持对 executor 的引用，以便 shutdown 时能正确关闭
_arq_executor = None


async def run_arq_worker():
    """Run ARQ worker in background using thread."""
    from concurrent.futures import ThreadPoolExecutor
    from arq import run_worker

    global _arq_executor

    def _run_worker():
        """Run worker in a separate thread with its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_worker(WorkerSettings))
        except Exception as e:
            logger.error("arq_worker_thread_error", error=str(e))
        finally:
            loop.close()

    _arq_executor = ThreadPoolExecutor(max_workers=1)
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_arq_executor, _run_worker)
    except asyncio.CancelledError:
        logger.info("arq_worker_cancelled")
    except Exception as e:
        logger.error("arq_worker_error", error=str(e))
    # shutdown 统一由 lifespan 管理，避免重复调用


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown."""
    # Startup
    setup_logging()
    health_task = None
    schedule_task = None

    print_status("YOLO 监控告警系统 v0.1.0 启动中...", "info")
    print_status("=" * 50, "info")

    # Initialize services
    print_status("正在初始化数据库连接...", "info")
    await db_service.init_db()
    print_status("[OK] MySQL 连接成功 (SQLAlchemy + aiomysql)", "success")

    print_status("正在创建默认管理员账号...", "info")
    await create_default_admin()
    print_status("[OK] 默认管理员已就绪", "success")

    print_status("正在初始化 MinIO 存储...", "info")
    await minio_service.ensure_bucket()
    print_status("[OK] MinIO 连接成功", "success")

    print_status("正在初始化 Redis 缓存...", "info")
    await alarm_dedup.get_redis()
    print_status("[OK] Redis 连接成功", "success")

    # Start ARQ Worker in background
    print_status("正在启动 ARQ Worker...", "info")
    worker_task = asyncio.create_task(run_arq_worker())
    await asyncio.sleep(1)  # Give worker time to start
    print_status("[OK] ARQ Worker 已启动", "success")

    # Start stream health recorder
    from app.core.health_recorder import record_stream_health
    health_task = asyncio.create_task(record_stream_health(stream_manager))

    # Load email notification config
    from app.core.email_notifier import email_notifier
    await email_notifier.load_config()

    # Start schedule checker for auto-start/stop streams
    from app.core.schedule_checker import check_schedules
    schedule_task = asyncio.create_task(check_schedules(stream_manager))

    # Log GPU availability
    providers = ort.get_available_providers()
    gpu_available = "CUDAExecutionProvider" in providers
    if gpu_available:
        print_status("[OK] GPU 加速可用 (CUDA)", "success")
    else:
        print_status("[WARN] GPU 不可用，使用 CPU 推理", "warning")

    # 自动恢复上次运行的流
    print_status("正在恢复历史流配置...", "info")
    try:
        from app.db import async_session
        from app.models.stream_config import StreamConfig
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(StreamConfig).where(StreamConfig.status == "running")
            )
            running_configs = result.scalars().all()
            restored = 0
            for cfg in running_configs:
                try:
                    r = await stream_manager.start_stream(
                        stream_id=cfg.stream_id,
                        stream_url=cfg.stream_url,
                        validate=False,  # 恢复时跳过验证，避免阻塞启动
                        alarm_types=cfg.alarm_types or ["helmet", "fire", "intrusion"],
                    )
                    if r["success"]:
                        restored += 1
                        print_status(f"  [OK] 已恢复流: {cfg.stream_id}", "success")
                    else:
                        print_status(f"  [FAIL] 恢复流 {cfg.stream_id} 失败: {r['message']}", "warning")
                except Exception as e:
                    print_status(f"  [FAIL] 恢复流 {cfg.stream_id} 异常: {e}", "warning")
            if running_configs:
                print_status(f"流恢复完成: {restored}/{len(running_configs)}", "info")
            else:
                print_status("无需恢复的流", "info")
    except Exception as e:
        print_status(f"流恢复跳过: {e}", "warning")

    print_status("=" * 50, "info")
    print_status(f"服务已就绪: http://localhost:{settings.APP_PORT}", "success")
    print_status(f"前端面板: http://localhost:{settings.APP_PORT}", "info")
    print_status(f"API 文档: http://localhost:{settings.APP_PORT}/docs", "info")
    print_status("=" * 50, "info")

    logger.info(
        "services_initialized",
        gpu_available=gpu_available,
        providers=providers,
    )

    yield

    # Shutdown
    print_status("正在关闭服务...", "warning")
    if health_task:
        health_task.cancel()
    if schedule_task:
        schedule_task.cancel()
    worker_task.cancel()
    if health_task:
        try:
            await health_task
        except asyncio.CancelledError:
            pass
    if schedule_task:
        try:
            await schedule_task
        except asyncio.CancelledError:
            pass
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await stream_manager.stop_all()
    await close_arq_pool()
    await alarm_dedup.close()
    from app.core.rate_limiter import RateLimiter
    await RateLimiter.close()
    minio_service.close()
    detector.close()
    await db_service.close()
    if _arq_executor:
        _arq_executor.shutdown(wait=False)
    print_status("服务已停止", "info")


# Create FastAPI app
app = FastAPI(
    title="YOLO 监控告警系统",
    description="轻量级监控流实时切片与多目标告警系统 - 支持安全帽检测、异物入侵、火灾烟雾识别",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF protection middleware
from app.core.csrf import CSRFMiddleware
app.add_middleware(CSRFMiddleware)

# Include routers
app.include_router(stream_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")

# WebSocket endpoint for real-time alarm push
from app.core.alarm_broadcaster import alarm_broadcaster


@app.websocket("/ws/alarms")
async def websocket_alarms(websocket: WebSocket):
    """WebSocket endpoint for real-time alarm notifications.

    Authentication: pass token as query param ?token=xxx (required).
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return

    from app.services.auth_service import get_current_user
    user = await get_current_user(token)
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await alarm_broadcaster.connect(websocket)
    try:
        while True:
            # Keep connection alive; clients may send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        await alarm_broadcaster.disconnect(websocket)
    except Exception:
        await alarm_broadcaster.disconnect(websocket)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Public paths (no auth required)
PUBLIC_PATHS = {"/login", "/static/login.html", "/health", "/docs", "/redoc", "/openapi.json"}


# ── 全局异常处理 ──
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return HTMLResponse(content="""
    <html><head><title>404</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>body{font-family:'DM Sans',-apple-system,sans-serif;background:#f8f7f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;color:#1c1917}
    .box{text-align:center}.code{font-size:4rem;font-weight:700;color:#d6d3d1;margin-bottom:12px}
    .msg{font-size:1rem;color:#78716c;margin-bottom:20px}.link{color:#1c1917;text-decoration:none;padding:8px 20px;border:1px solid #e8e6e3;border-radius:8px;font-size:0.82rem;transition:0.15s}
    .link:hover{border-color:#a8a29e;background:#f3f2f0}</style></head>
    <body><div class="box"><div class="code">404</div><div class="msg">页面不存在</div><a href="/" class="link">返回主页</a></div></body></html>
    """, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return HTMLResponse(content="""
    <html><head><title>500</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>body{font-family:'DM Sans',-apple-system,sans-serif;background:#f8f7f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;color:#1c1917}
    .box{text-align:center}.code{font-size:4rem;font-weight:700;color:#fca5a5;margin-bottom:12px}
    .msg{font-size:1rem;color:#78716c;margin-bottom:20px}.link{color:#1c1917;text-decoration:none;padding:8px 20px;border:1px solid #e8e6e3;border-radius:8px;transition:0.15s}
    .link:hover{border-color:#a8a29e;background:#f3f2f0}</style></head>
    <body><div class="box"><div class="code">500</div><div class="msg">服务器内部错误</div><a href="/" class="link">返回主页</a></div></body></html>
    """, status_code=500)

# 需要记录操作日志的 API — key=(method, path), value=action name
# 新增需要审计的接口时，在此字典中添加映射即可
_LOG_ACTION_MAP = {
    ("POST", "/api/v1/stream/start"): "stream_start",
    ("POST", "/api/v1/stream/stop"): "stream_stop",
    ("POST", "/api/v1/stream/detect/upload"): "detect_upload",
    ("POST", "/api/v1/stream/detect"): "detect_url",
    ("DELETE", "/api/v1/stream/alarms"): "alarm_clear",
    ("POST", "/api/v1/auth/login"): "login",
    ("POST", "/api/v1/auth/register"): "register",
    ("POST", "/api/v1/auth/logout"): "logout",
    ("POST", "/api/annotations/save"): "annotation_save",
}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Allow public paths, API auth endpoints, and static assets
    if (path in PUBLIC_PATHS
        or path.startswith("/api/v1/auth/")
        or path.startswith("/static/")
        or path.startswith("/docs")
        or path.startswith("/redoc")
        or path.startswith("/openapi")):
        return await call_next(request)

    # JWT: check Authorization header or cookie
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("token")

    user = await get_current_user(token)
    if not user:
        logger.debug("auth_blocked", path=path, has_cookie=bool(request.cookies.get("token")))
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "未登录或 token 已过期"})
        return RedirectResponse(url="/login", status_code=302)

    request.state.user = user
    response = await call_next(request)

    # 操作日志记录（异步，不阻塞响应）
    log_key = (request.method, path)
    action = _LOG_ACTION_MAP.get(log_key)
    if action and 200 <= response.status_code < 400:
        try:
            from app.services.operation_log_service import write_log
            asyncio.create_task(write_log(
                action=action,
                user_id=user.get("id"),
                username=user.get("username"),
                target_type="api",
                target_id=path,
                ip_address=request.client.host if request.client else None,
            ))
        except Exception:
            pass  # 日志记录失败不影响正常响应

    return response

# === 标注工具 API ===
ANNOTATE_DIR = Path(__file__).parent.parent / "fire_smoke_data" / "to_annotate"
LABELS_DIR = Path(__file__).parent.parent / "fire_yolo" / "train"

@app.get("/api/annotations/files")
async def list_annotate_files():
    """列出待标注的图片文件（优先从数据库读取）"""
    files = []

    # 从数据库读取已记录的图片
    try:
        from app.db import async_session
        from app.models.annotation_image import AnnotationImage
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(AnnotationImage.filename, AnnotationImage.is_annotated, AnnotationImage.box_count)
                .order_by(AnnotationImage.id)
            )
            db_files = {r[0]: {"is_annotated": r[1], "box_count": r[2]} for r in result.all()}
    except Exception:
        db_files = {}

    # 扫描目录
    if ANNOTATE_DIR.exists():
        for f in sorted(ANNOTATE_DIR.iterdir()):
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                name = f.name
                if name in db_files:
                    files.append({"name": name, "annotated": db_files[name]["is_annotated"], "box_count": db_files[name]["box_count"]})
                else:
                    # Fallback: check label file
                    lbl_name = f.stem + ".txt"
                    lbl_path = LABELS_DIR / "labels" / lbl_name
                    files.append({"name": name, "annotated": lbl_path.exists(), "box_count": 0})

    return {"files": files}

@app.get("/api/annotations/image/{filename}")
async def get_annotate_image(filename: str):
    """获取待标注的图片"""
    # Path traversal protection: reject filenames with path separators
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    img_path = (ANNOTATE_DIR / filename).resolve()
    # Ensure resolved path is still within ANNOTATE_DIR
    if not str(img_path).startswith(str(ANNOTATE_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if img_path.exists():
        return FileResponse(str(img_path), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Image not found")

@app.get("/api/annotations/box/{filename}")
async def get_annotate_boxes(filename: str):
    """获取已有的标注（优先从数据库读取）"""
    boxes = []

    # Try database first
    try:
        from app.db import async_session
        from app.models.annotation_image import AnnotationImage
        from app.models.annotation_box import AnnotationBox
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(AnnotationImage.id).where(AnnotationImage.filename == filename)
            )
            image_id = result.scalar_one_or_none()
            if image_id:
                result = await session.execute(
                    select(AnnotationBox.class_id, AnnotationBox.cx, AnnotationBox.cy, AnnotationBox.bw, AnnotationBox.bh)
                    .where(AnnotationBox.image_id == image_id)
                    .order_by(AnnotationBox.id)
                )
                for r in result.all():
                    boxes.append({"class": r[0], "cx": r[1], "cy": r[2], "w": r[3], "h": r[4]})
                return {"boxes": boxes}
    except Exception:
        pass

    # Fallback to file
    lbl_name = Path(filename).stem + ".txt"
    lbl_path = LABELS_DIR / "labels" / lbl_name
    if lbl_path.exists():
        with open(lbl_path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    cls, cx, cy, w, h = int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                    boxes.append({"class": cls, "cx": cx, "cy": cy, "w": w, "h": h})
    return {"boxes": boxes}

@app.post("/api/annotations/save")
async def save_annotation(data: dict, request: Request = None):
    """保存标注（文件 + 数据库）"""
    filename = data.get("filename", "")
    content = data.get("content", "")
    dataset_name = data.get("dataset_name", "default")

    # 保存到训练集标注目录
    lbl_name = Path(filename).stem + ".txt"
    lbl_path = LABELS_DIR / "labels" / lbl_name
    lbl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lbl_path, "w") as f:
        f.write(content)

    # 复制图片到训练集
    src_img = ANNOTATE_DIR / filename
    dst_img = LABELS_DIR / "images" / filename
    dst_img.parent.mkdir(parents=True, exist_ok=True)
    if src_img.exists() and not dst_img.exists():
        shutil.copy2(src_img, dst_img)

    # ── 入库 (SQLAlchemy ORM) ──
    try:
        import cv2
        from app.db import async_session
        from app.models.annotation_image import AnnotationImage
        from app.models.annotation_box import AnnotationBox
        from sqlalchemy import select

        img_w, img_h = 0, 0
        if src_img.exists():
            frame = await asyncio.to_thread(cv2.imread, str(src_img))
            if frame is not None:
                img_h, img_w = frame.shape[:2]

        file_size = src_img.stat().st_size if src_img.exists() else 0
        file_path = str(dst_img.relative_to(Path(__file__).parent.parent)) if dst_img.exists() else str(src_img)

        username = None
        if request and hasattr(request.state, "user"):
            username = request.state.user.get("username")

        box_count = len(content.strip().splitlines()) if content.strip() else 0

        async with async_session() as session:
            result = await session.execute(
                select(AnnotationImage).where(AnnotationImage.filename == filename)
            )
            image = result.scalar_one_or_none()

            if image:
                image.file_path = file_path
                image.file_size = file_size
                image.width = img_w
                image.height = img_h
                image.dataset_name = dataset_name
                image.is_annotated = True
                image.box_count = box_count
                image.update_by = username
                image_id = image.id
            else:
                image = AnnotationImage(
                    filename=filename, file_path=file_path, file_size=file_size,
                    width=img_w, height=img_h, dataset_name=dataset_name,
                    is_annotated=True, box_count=box_count, create_by=username,
                )
                session.add(image)
                await session.flush()
                image_id = image.id

            await session.execute(
                select(AnnotationBox).where(AnnotationBox.image_id == image_id).delete()
            )

            if content.strip():
                class_map = {0: "fire", 1: "smoke"}
                for line in content.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        cls_id = int(parts[0])
                        cx, cy, bw, bh = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                        cls_name = class_map.get(cls_id, f"class_{cls_id}")
                        session.add(AnnotationBox(
                            image_id=image_id, class_id=cls_id, class_name=cls_name,
                            cx=cx, cy=cy, bw=bw, bh=bh, create_by=username,
                        ))

            await session.commit()
            logger.info("annotation_saved", filename=filename, image_id=image_id, boxes=box_count)

    except Exception as e:
        logger.error("annotation_db_save_error", filename=filename, error=str(e))

    return {"success": True, "message": f"Saved {filename}"}


@app.post("/api/annotations/upload")
async def upload_to_annotate(file: UploadFile = File(...)):
    """上传图片到待标注目录（用于检测→标注联动）"""
    safe_name = Path(file.filename).name
    if '..' in safe_name or '/' in safe_name or '\\' in safe_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    dst = (ANNOTATE_DIR / safe_name).resolve()
    if not str(dst).startswith(str(ANNOTATE_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件名")
    ANNOTATE_DIR.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    with open(dst, "wb") as f:
        f.write(content)
    return {"success": True, "filename": safe_name}


@app.get("/metrics", summary="Prometheus 指标", include_in_schema=False)
async def metrics_endpoint():
    """Prometheus-compatible metrics endpoint."""
    from app.core.metrics import render_metrics, set_gauge
    from fastapi.responses import PlainTextResponse

    set_gauge("argus_active_streams", stream_manager.active_streams)
    set_gauge("argus_max_streams", settings.MAX_CONCURRENT_STREAMS)

    return PlainTextResponse(content=render_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/health", summary="健康检查", description="返回系统健康状态，包括活跃流数量、队列深度、GPU可用性")
async def health_check():
    """健康检查接口。

    返回:
        - status: 系统状态
        - active_streams: 活跃流数量
        - queue_depth: 告警队列深度
        - gpu_available: GPU是否可用
    """
    providers = ort.get_available_providers()
    gpu_available = "CUDAExecutionProvider" in providers

    # 活跃流为空时跳过 Redis SCAN，节省资源
    if stream_manager.active_streams > 0:
        queue_depth = await alarm_dedup.get_queue_depth()
    else:
        queue_depth = 0

    # 每条流的健康状态
    streams_health = []
    for info in stream_manager.get_streams_info():
        streams_health.append({
            "stream_id": info.get("stream_id"),
            "status": info.get("status"),
            "alarm_count": info.get("alarm_count", 0),
        })

    # 数据库连接池状态
    from app.db import get_pool_status
    pool_status = get_pool_status()

    # GPU memory status
    from app.core.gpu_monitor import gpu_monitor
    gpu_status = gpu_monitor.get_status_summary()

    return {
        "status": "正常",
        "active_streams": stream_manager.active_streams,
        "queue_depth": queue_depth,
        "gpu_available": gpu_available,
        "gpu": gpu_status,
        "streams": streams_health,
        "db_pool": pool_status,
    }


@app.get("/", summary="调试面板", description="返回可视化调试面板页面")
async def root():
    """可视化调试面板。"""
    index_file = Path(__file__).parent / "static" / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), media_type="text/html")
    return {
        "name": "YOLO 监控告警系统",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "dashboard": "/static/index.html",
        "annotate": "/static/annotate.html",
    }


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page():
    """登录页面。"""
    login_file = Path(__file__).parent / "static" / "login.html"
    if login_file.exists():
        return FileResponse(str(login_file), media_type="text/html")
    return HTMLResponse("<h1>login.html not found</h1>", status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )
