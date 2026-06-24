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

import onnxruntime as ort
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.stream import router as stream_router
from app.config import settings
from app.core.alarm_dedup import alarm_dedup
from app.core.detector import detector
from app.core.stream_processor import stream_manager
from app.services.database import db_service
from app.services.minio_client import minio_service
from app.services.worker_tasks import WorkerSettings, close_arq_pool
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
        loop = asyncio.get_event_loop()
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

    print_status("YOLO 监控告警系统 v0.1.0 启动中...", "info")
    print_status("=" * 50, "info")

    # Initialize services
    print_status("正在初始化数据库连接...", "info")
    await db_service.init_db()
    print_status("[OK] PostgreSQL 连接成功", "success")

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

    # Log GPU availability
    providers = ort.get_available_providers()
    gpu_available = "CUDAExecutionProvider" in providers
    if gpu_available:
        print_status("[OK] GPU 加速可用 (CUDA)", "success")
    else:
        print_status("[WARN] GPU 不可用，使用 CPU 推理", "warning")

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
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await stream_manager.stop_all()
    await close_arq_pool()
    await alarm_dedup.close()
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

# Include routers
app.include_router(stream_router, prefix="/api/v1")

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# === 标注工具 API ===
ANNOTATE_DIR = Path(__file__).parent.parent / "fire_smoke_data" / "to_annotate"
LABELS_DIR = Path(__file__).parent.parent / "fire_yolo" / "train"

@app.get("/api/annotations/files")
async def list_annotate_files():
    """列出待标注的图片文件"""
    files = []
    if ANNOTATE_DIR.exists():
        for f in sorted(ANNOTATE_DIR.iterdir()):
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                lbl_name = f.stem + ".txt"
                lbl_path = LABELS_DIR / "labels" / lbl_name
                files.append({"name": f.name, "annotated": lbl_path.exists()})
    return {"files": files}

@app.get("/api/annotations/image/{filename}")
async def get_annotate_image(filename: str):
    """获取待标注的图片"""
    img_path = ANNOTATE_DIR / filename
    if img_path.exists():
        return FileResponse(str(img_path), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Image not found")

@app.get("/api/annotations/box/{filename}")
async def get_annotate_boxes(filename: str):
    """获取已有的标注"""
    lbl_name = Path(filename).stem + ".txt"
    lbl_path = LABELS_DIR / "labels" / lbl_name
    boxes = []
    if lbl_path.exists():
        with open(lbl_path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    cls, cx, cy, w, h = int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                    boxes.append({"class": cls, "cx": cx, "cy": cy, "w": w, "h": h})
    return {"boxes": boxes}

@app.post("/api/annotations/save")
async def save_annotation(data: dict):
    """保存标注"""
    filename = data.get("filename", "")
    content = data.get("content", "")
    
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
    
    return {"success": True, "message": f"Saved {filename}"}


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

    return {
        "status": "正常",
        "active_streams": stream_manager.active_streams,
        "queue_depth": queue_depth,
        "gpu_available": gpu_available,
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )
