import asyncio
import io
from typing import List, Optional

import cv2
import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.core.rate_limiter import RateLimiter

from app.config import settings
from app.core.detector import detector
from app.core.stream_processor import stream_manager
from app.utils.logger import get_logger


async def log_operation(action: str, username: str = None, detail: str = None, request: Request = None):
    """记录操作日志到数据库"""
    try:
        from app.db import async_session
        from app.models.operation_log import OperationLog
        ip = request.client.host if request and request.client else None
        async with async_session() as session:
            session.add(OperationLog(
                action=action,
                username=username,
                detail=detail,
                ip_address=ip,
                create_by=username,
            ))
            await session.commit()
    except Exception:
        pass

logger = get_logger(__name__)

router = APIRouter(prefix="/stream", tags=["流处理管理"])


# 请求/响应模型
class StreamStartRequest(BaseModel):
    """启动流处理请求模型"""

    stream_url: str = Field(..., description="监控流地址 (RTSP/RTMP)", examples=["rtsp://admin:password@192.168.1.100:554/stream1"])
    stream_id: str = Field(..., description="流唯一标识符", min_length=1, max_length=64, examples=["camera-001"])
    validate_stream: bool = Field(True, description="是否在启动前验证流可用性")
    alarm_types: List[str] = Field(
        default=["helmet", "fire", "intrusion"],
        description="要检测的告警类型: helmet(安全帽), fire(火灾), intrusion(入侵检测)",
        examples=[["helmet", "fire", "intrusion"]]
    )
    roi_x: Optional[int] = Field(None, description="检测区域左上角 X 像素坐标")
    roi_y: Optional[int] = Field(None, description="检测区域左上角 Y 像素坐标")
    roi_w: Optional[int] = Field(None, description="检测区域宽度 (像素)")
    roi_h: Optional[int] = Field(None, description="检测区域高度 (像素)")


class StreamStopRequest(BaseModel):
    """停止流处理请求模型"""

    stream_id: str = Field(..., description="要停止的流标识符", examples=["camera-001"])


class StreamResponse(BaseModel):
    """流操作响应模型"""

    success: bool = Field(..., description="操作是否成功")
    stream_id: Optional[str] = Field(None, description="流标识符")
    message: str = Field(..., description="提示信息")


class StreamStatusResponse(BaseModel):
    """流状态响应模型"""

    stream_id: str = Field(..., description="流标识符")
    url: str = Field(..., description="流地址")
    status: str = Field(..., description="流状态")


async def _save_stream_config(stream_id: str, stream_url: str, alarm_types: list, status: str,
                              username: str = None, roi: tuple = None):
    """保存/更新流配置到数据库。"""
    try:
        from app.db import async_session
        from app.models.stream_config import StreamConfig
        from sqlalchemy import select
        from datetime import datetime

        async with async_session() as session:
            result = await session.execute(select(StreamConfig).where(StreamConfig.stream_id == stream_id))
            cfg = result.scalar_one_or_none()
            if cfg:
                cfg.stream_url = stream_url
                cfg.alarm_types = alarm_types
                cfg.status = status
                cfg.error_message = None
                if roi:
                    cfg.roi_x, cfg.roi_y, cfg.roi_w, cfg.roi_h = roi
                if status == "running":
                    cfg.started_at = datetime.now()
                elif status in ("stopped", "idle"):
                    cfg.stopped_at = datetime.now()
                cfg.update_by = username
            else:
                cfg = StreamConfig(
                    stream_id=stream_id,
                    stream_url=stream_url,
                    alarm_types=alarm_types,
                    status=status,
                    roi_x=roi[0] if roi else None,
                    roi_y=roi[1] if roi else None,
                    roi_w=roi[2] if roi else None,
                    roi_h=roi[3] if roi else None,
                    started_at=datetime.now() if status == "running" else None,
                    create_by=username,
                )
                session.add(cfg)
            await session.commit()
    except Exception as e:
        logger.error("save_stream_config_error", stream_id=stream_id, error=str(e))


@router.post("/start", response_model=StreamResponse, summary="启动流处理", description="启动对指定监控流的实时YOLO检测处理")
async def start_stream(request: StreamStartRequest, req: Request = None):
    """启动流处理接口。

    开始对指定的监控流进行实时目标检测，支持安全帽、动物、火灾烟雾、异物入侵检测。
    当并发流数量达到上限时返回 429 错误。

    - **stream_url**: 监控流地址 (RTSP/RTMP)
    - **stream_id**: 流唯一标识符
    - **validate**: 是否在启动前验证流的可用性 (默认开启)
    - **alarm_types**: 要检测的告警类型列表 (helmet=安全帽, animal=动物, fire=火灾, intrusion=异物入侵)
    """
    logger.info(
        "api_start_stream",
        stream_id=request.stream_id,
        url=request.stream_url,
        validate=request.validate_stream,
        alarm_types=request.alarm_types,
    )

    username = None
    if req and hasattr(req.state, "user"):
        username = req.state.user.get("username")

    # 启动流处理
    roi = None
    if request.roi_x is not None and request.roi_y is not None and request.roi_w is not None and request.roi_h is not None:
        roi = (request.roi_x, request.roi_y, request.roi_w, request.roi_h)

    result = await stream_manager.start_stream(
        stream_id=request.stream_id,
        stream_url=request.stream_url,
        validate=request.validate_stream,
        alarm_types=request.alarm_types,
        roi=roi,
    )

    if not result["success"]:
        # 根据错误类型返回不同的状态码
        if "已存在" in result["message"]:
            raise HTTPException(status_code=409, detail=result["message"])
        elif "验证失败" in result["message"]:
            raise HTTPException(status_code=400, detail=result["message"])
        elif "最大并发" in result["message"]:
            raise HTTPException(status_code=429, detail=result["message"])
        else:
            raise HTTPException(status_code=500, detail=result["message"])

    # 持久化流配置到数据库
    await _save_stream_config(request.stream_id, request.stream_url, request.alarm_types, "running", username, roi=roi)

    await log_operation("start_stream", username, f"启动流 {request.stream_id}", req)

    return StreamResponse(
        success=True,
        stream_id=request.stream_id,
        message=result["message"],
    )


@router.post("/stop", response_model=StreamResponse, summary="停止流处理", description="优雅停止指定流的处理并释放资源")
async def stop_stream(request: StreamStopRequest, req: Request = None):
    """停止流处理接口。

    优雅停止指定流的处理器并释放相关资源。
    """
    logger.info("api_stop_stream", stream_id=request.stream_id)

    username = None
    if req and hasattr(req.state, "user"):
        username = req.state.user.get("username")

    success = await stream_manager.stop_stream(request.stream_id)

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"流 '{request.stream_id}' 未找到",
        )

    await log_operation("stop_stream", username, f"停止流 {request.stream_id}", req)

    return StreamResponse(
        success=True,
        stream_id=request.stream_id,
        message="流处理已停止",
    )


@router.get("/list", summary="获取流列表", description="获取当前所有活跃的流列表及其状态")
async def list_streams():
    """获取流列表接口。

    返回当前所有正在处理的流信息，包括监测类型和运行状态。
    """
    return {
        "active_streams": stream_manager.active_streams,
        "max_streams": settings.MAX_CONCURRENT_STREAMS,
        "streams": stream_manager.get_streams_info(),
    }


@router.get("/alarms", summary="查询告警列表", description="查询告警记录，支持按流ID、告警类型和严重级别筛选")
async def get_alarms(
    stream_id: Optional[str] = None,
    alarm_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """查询告警列表接口。

    - **stream_id**: 按流ID筛选（可选）
    - **alarm_type**: 按告警类型筛选（可选）: helmet, animal, fire, intrusion
    - **severity**: 按严重级别筛选（可选）: normal, important, critical
    - **limit**: 返回记录数（默认100，最大500）
    - **offset**: 偏移量（默认0）
    """
    # Validate bounds
    if limit < 1:
        limit = 1
    elif limit > 500:
        limit = 500
    if offset < 0:
        offset = 0

    from app.services.database import db_service

    alarms = await db_service.get_alarms(
        stream_id=stream_id,
        alarm_type=alarm_type,
        severity=severity,
        limit=limit,
        offset=offset,
    )

    return {
        "total": len(alarms),
        "alarms": alarms,
    }


@router.get("/image/{image_path:path}", summary="获取告警图片", description="根据图片路径获取告警图片")
async def get_alarm_image(image_path: str):
    """获取告警图片接口。

    - **image_path**: MinIO 中的图片路径
    """
    from fastapi.responses import Response
    from app.services.minio_client import minio_service
    from minio.error import S3Error

    try:
        client = minio_service.get_client()
        bucket = settings.MINIO_BUCKET

        # 从 MinIO 获取图片
        response = await asyncio.to_thread(
            client.get_object,
            bucket,
            image_path,
        )

        try:
            image_data = response.read()
        finally:
            # 确保无论读取是否成功都释放连接
            response.close()
            response.release_conn()

        media_type = "image/png" if image_path.endswith(".png") else "image/jpeg"

        return Response(
            content=image_data,
            media_type=media_type,
            headers={"Cache-Control": "max-age=3600"},
        )
    except S3Error as e:
        logger.error("image_fetch_error", error=str(e), path=image_path)
        raise HTTPException(status_code=404, detail="图片不存在")
    except Exception as e:
        logger.error("image_fetch_error", error=str(e), path=image_path)
        raise HTTPException(status_code=500, detail="获取图片失败")


@router.delete("/alarms/{alarm_id}", summary="删除告警记录", description="根据ID删除告警记录")
async def delete_alarm(alarm_id: int):
    """删除告警记录接口。

    - **alarm_id**: 告警记录ID
    """
    from app.services.database import db_service

    deleted = await db_service.delete_alarm(alarm_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="告警记录不存在")

    return {"success": True, "message": f"告警记录 {alarm_id} 已删除"}


@router.delete("/alarms", summary="清空告警记录", description="删除所有告警记录")
async def delete_all_alarms(request: Request):
    """清空所有告警记录接口（仅管理员）。"""
    from app.services.auth_service import has_permission, Permission
    user = getattr(request.state, "user", None)
    if not user or not has_permission(user.get("role", ""), Permission.MANAGE_ALARM):
        raise HTTPException(status_code=403, detail="权限不足")
    from app.services.database import db_service
    count = await db_service.delete_all_alarms()
    return {"success": True, "message": f"已删除 {count} 条告警记录"}


# ── 调试接口 ──


class DetectRequest(BaseModel):
    """图片检测请求模型"""
    image_url: str = Field(..., description="图片地址（支持 HTTP/HTTPS 直链或本地路径）")
    model: str = Field("general", description="模型名称: general / fire_smoke / helmet")
    confidence: float = Field(0.3, description="置信度阈值", ge=0.0, le=1.0)


class DetectResult(BaseModel):
    class_name: str
    class_id: int
    confidence: float
    bbox: List[float]


@router.post("/detect", summary="图片检测调试", description="传入图片地址（HTTP URL 或本地路径），返回模型识别结果")
@RateLimiter.limit(max_requests=20, window_seconds=60)
async def detect_image(request: DetectRequest, req: Request = None):
    """图片检测调试接口。

    传入图片地址（HTTP URL 或本地路径），返回指定模型的识别结果。

    - **image_url**: 图片地址
    - **model**: 使用的模型 (general/helmet/fire_smoke)
    - **confidence**: 置信度阈值（可选）
    """
    try:
        # 下载或读取图片
        if request.image_url.startswith(("http://", "https://")):
            # SSRF 防护：禁止访问内网地址
            from urllib.parse import urlparse
            import ipaddress
            parsed = urlparse(request.image_url)
            hostname = parsed.hostname or ""
            # 阻止内网 IP、localhost、metadata 地址
            blocked = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"]
            if hostname in blocked:
                raise HTTPException(status_code=400, detail="禁止访问内网地址")
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    raise HTTPException(status_code=400, detail="禁止访问内网地址")
            except ValueError:
                pass  # 域名，继续

            async with httpx.AsyncClient(timeout=30, proxy=None) as client:
                resp = await client.get(request.image_url)
                resp.raise_for_status()
                img_bytes = resp.content
            img_array = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        else:
            frame = await asyncio.to_thread(cv2.imread, request.image_url)

        if frame is None:
            raise HTTPException(status_code=400, detail="无法读取图片")

        # 选择模型
        model_name = request.model
        if model_name not in ("general", "helmet", "fire_smoke"):
            raise HTTPException(status_code=400, detail=f"不支持的模型: {model_name}")

        # 执行检测
        detections, inference_time = await detector.detect_with_model(
            frame, model_name, confidence_threshold=request.confidence
        )

        # 格式化结果
        results = []
        for i in range(len(detections)):
            class_id = int(detections.class_id[i])
            confidence = float(detections.confidence[i])
            bbox = detections.xyxy[i].tolist()
            class_name = detector.get_class_name(model_name, class_id)

            results.append({
                "class_id": class_id,
                "class_name": class_name,
                "confidence": round(confidence, 4),
                "bbox": [round(x, 1) for x in bbox],
                "bbox_format": "x1_y1_x2_y2",
            })

        return {
            "success": True,
            "model": model_name,
            "inference_time_ms": round(inference_time, 1),
            "image_size": {"width": frame.shape[1], "height": frame.shape[0]},
            "detections_count": len(results),
            "detections": results,
        }

    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"下载图片失败: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("detect_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@router.post("/detect/upload", summary="上传图片检测", description="上传图片文件进行检测，返回识别结果")
@RateLimiter.limit(max_requests=20, window_seconds=60)
async def detect_upload(
    file: UploadFile = File(..., description="图片文件"),
    model: str = Form("general", description="模型: general/helmet/fire_smoke"),
    confidence: float = Form(0.3, description="置信度阈值"),
    request: Request = None,
):
    """上传图片检测接口。

    支持 jpg/png/bmp 格式，返回检测框、类别和置信度。检测结果自动存入数据库。
    """
    try:
        # 读取上传的图片（限制 10MB）
        MAX_SIZE = 10 * 1024 * 1024
        img_bytes = await file.read()
        if len(img_bytes) > MAX_SIZE:
            raise HTTPException(status_code=400, detail="文件过大，最大支持 10MB")
        img_array = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if frame is None:
            raise HTTPException(status_code=400, detail="无法读取图片，请确保是有效的图片文件")

        # 选择模型
        if model not in ("general", "helmet", "fire_smoke"):
            raise HTTPException(status_code=400, detail=f"不支持的模型: {model}")

        # 执行检测
        detections, inference_time = await detector.detect_with_model(
            frame, model, confidence_threshold=confidence
        )

        # 格式化结果
        results = []
        for i in range(len(detections)):
            class_id = int(detections.class_id[i])
            conf = float(detections.confidence[i])
            bbox = detections.xyxy[i].tolist()
            class_name = detector.get_class_name(model, class_id)

            results.append({
                "class_id": class_id,
                "class_name": class_name,
                "confidence": round(conf, 4),
                "bbox": [round(x, 1) for x in bbox],
                "bbox_format": "x1_y1_x2_y2",
            })

        # 上传图片到 MinIO
        image_path = None
        try:
            from app.services.minio_client import minio_service
            image_path = await minio_service.upload_image(img_bytes, stream_id="detect")
        except Exception as e:
            logger.warning("detect_image_upload_failed", error=str(e))

        # 获取当前用户
        user_id = None
        username = None
        if request and hasattr(request.state, "user"):
            user_id = request.state.user.get("id")
            username = request.state.user.get("username")

        # 存入数据库 (SQLAlchemy ORM)
        from app.db import async_session
        from app.models.detection_result import DetectionResult
        from app.models.detection_box import DetectionBox

        async with async_session() as session:
            det_result = DetectionResult(
                filename=file.filename,
                image_path=image_path,
                model_name=model,
                confidence_threshold=confidence,
                inference_time_ms=round(inference_time, 1),
                image_width=frame.shape[1],
                image_height=frame.shape[0],
                detections_count=len(results),
                user_id=user_id,
                create_by=username,
            )
            session.add(det_result)
            await session.flush()

            for r in results:
                session.add(DetectionBox(
                    result_id=det_result.id,
                    class_id=r["class_id"],
                    class_name=r["class_name"],
                    confidence=r["confidence"],
                    bbox_x1=r["bbox"][0],
                    bbox_y1=r["bbox"][1],
                    bbox_x2=r["bbox"][2],
                    bbox_y2=r["bbox"][3],
                    create_by=username,
                ))
            await session.commit()
            result_id = det_result.id

        logger.info("detection_saved", result_id=result_id, model=model, count=len(results))

        return {
            "success": True,
            "result_id": result_id,
            "model": model,
            "inference_time_ms": round(inference_time, 1),
            "image_size": {"width": frame.shape[1], "height": frame.shape[0]},
            "detections_count": len(results),
            "detections": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("detect_upload_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@router.get("/detect/history", summary="检测历史列表")
async def detect_history(limit: int = 20, offset: int = 0, model: str = None):
    from app.db import async_session
    from app.models.detection_result import DetectionResult
    from app.models.detection_box import DetectionBox
    from sqlalchemy import select, func, text

    async with async_session() as session:
        # 总数（支持模型筛选）
        count_stmt = select(func.count(DetectionResult.id))
        if model:
            count_stmt = count_stmt.where(DetectionResult.model_name == model)
        total = await session.scalar(count_stmt)

        # 类别汇总（支持模型筛选）
        summary_query = text("""
            SELECT dr.id, GROUP_CONCAT(DISTINCT db.class_name SEPARATOR ' · ') as class_summary
            FROM detection_result dr
            LEFT JOIN detection_box db ON dr.id = db.result_id
            WHERE (:model IS NULL OR dr.model_name = :model)
            GROUP BY dr.id
        """)
        summary_result = await session.execute(summary_query, {"model": model})
        summary_map = {row[0]: row[1] for row in summary_result.all()}

        # 查询列表（支持模型筛选）
        stmt = select(DetectionResult).order_by(DetectionResult.detected_at.desc())
        if model:
            stmt = stmt.where(DetectionResult.model_name == model)
        stmt = stmt.limit(limit).offset(offset)
        items = []
        for r in (await session.execute(stmt)).scalars().all():
            items.append({
                "id": r.id,
                "filename": r.filename,
                "image_path": r.image_path,
                "model_name": r.model_name,
                "confidence_threshold": r.confidence_threshold,
                "inference_time_ms": r.inference_time_ms,
                "image_width": r.image_width,
                "image_height": r.image_height,
                "detections_count": r.detections_count,
                "class_summary": (summary_map.get(r.id, "") or "").split(" · ") if summary_map.get(r.id) else [],
                "create_by": r.create_by,
                "detected_at": str(r.detected_at) if r.detected_at else None,
            })
    return {"total": total, "items": items}


@router.get("/detect/{result_id}", summary="检测详情")
async def detect_detail(result_id: int):
    from app.db import async_session
    from app.models.detection_result import DetectionResult
    from app.models.detection_box import DetectionBox
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(DetectionResult).where(DetectionResult.id == result_id)
        )
        det = result.scalar_one_or_none()
        if not det:
            raise HTTPException(status_code=404, detail="记录不存在")

        boxes_result = await session.execute(
            select(DetectionBox)
            .where(DetectionBox.result_id == result_id)
            .order_by(DetectionBox.id)
        )
        boxes = [
            {
                "class_id": b.class_id,
                "class_name": b.class_name,
                "confidence": b.confidence,
                "bbox": [b.bbox_x1, b.bbox_y1, b.bbox_x2, b.bbox_y2],
            }
            for b in boxes_result.scalars().all()
        ]

    return {
        "id": det.id,
        "filename": det.filename,
        "image_path": det.image_path,
        "model_name": det.model_name,
        "confidence_threshold": det.confidence_threshold,
        "inference_time_ms": det.inference_time_ms,
        "image_width": det.image_width,
        "image_height": det.image_height,
        "detections_count": det.detections_count,
        "detected_at": str(det.detected_at) if det.detected_at else None,
        "detections": boxes,
    }


@router.delete("/detect/{result_id}", summary="删除检测记录")
async def detect_delete(result_id: int):
    from app.db import async_session
    from app.models.detection_result import DetectionResult
    from app.models.detection_box import DetectionBox
    from sqlalchemy import select, delete as sa_delete

    async with async_session() as session:
        result = await session.execute(select(DetectionResult).where(DetectionResult.id == result_id))
        det = result.scalar_one_or_none()
        if not det:
            raise HTTPException(status_code=404, detail="记录不存在")
        await session.execute(sa_delete(DetectionBox).where(DetectionBox.result_id == result_id))
        await session.delete(det)
        await session.commit()
    return {"success": True, "message": "已删除"}


@router.delete("/detect", summary="清空检测记录")
async def detect_delete_all(request: Request):
    from app.services.auth_service import has_permission, Permission
    user = getattr(request.state, "user", None)
    if not user or not has_permission(user.get("role", ""), Permission.MANAGE_ALARM):
        raise HTTPException(status_code=403, detail="权限不足")
    from app.db import async_session
    from app.models.detection_result import DetectionResult
    from app.models.detection_box import DetectionBox
    from sqlalchemy import delete as sa_delete, func, select

    async with async_session() as session:
        total = await session.scalar(select(func.count(DetectionResult.id)))
        await session.execute(sa_delete(DetectionBox))
        await session.execute(sa_delete(DetectionResult))
        await session.commit()
    return {"success": True, "message": f"已删除 {total} 条记录"}


# ── Dashboard Statistics ──

@router.get("/dashboard")
async def dashboard_stats():
    """首页统计概览"""
    from app.db import async_session
    from app.models.alarm_record import AlarmRecord
    from app.models.detection_result import DetectionResult
    from app.models.stream_config import StreamConfig
    from sqlalchemy import select, func

    async with async_session() as session:
        # 告警总数
        alarm_total = await session.scalar(select(func.count(AlarmRecord.id))) or 0
        # 今日告警
        from datetime import datetime, timedelta
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        alarm_today = await session.scalar(
            select(func.count(AlarmRecord.id)).where(AlarmRecord.detected_at >= today)
        ) or 0
        # 告警类型分布
        type_result = await session.execute(
            select(AlarmRecord.alarm_type, func.count(AlarmRecord.id))
            .group_by(AlarmRecord.alarm_type)
        )
        alarm_type_dist = {r[0]: r[1] for r in type_result.all()}
        # 检测总数
        detect_total = await session.scalar(select(func.count(DetectionResult.id))) or 0
        # 活跃流数
        stream_count = await session.scalar(
            select(func.count(StreamConfig.id)).where(StreamConfig.status == "running")
        ) or 0

    return {
        "success": True,
        "alarm_total": alarm_total,
        "alarm_today": alarm_today,
        "alarm_type_dist": alarm_type_dist,
        "detect_total": detect_total,
        "stream_count": stream_count,
    }


@router.get("/dashboard/trend")
async def dashboard_trend(days: int = 7):
    """近 N 天告警趋势"""
    from app.db import async_session
    from app.models.alarm_record import AlarmRecord
    from sqlalchemy import select, func, text
    from datetime import datetime, timedelta

    async with async_session() as session:
        result = await session.execute(text("""
            SELECT DATE(detected_at) as day, COUNT(*) as cnt
            FROM alarm_record
            WHERE detected_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
            GROUP BY DATE(detected_at)
            ORDER BY day
        """), {"days": days})
        trend = [{"date": str(r[0]), "count": r[1]} for r in result.all()]

    return {"success": True, "trend": trend}


@router.post("/detect/video", summary="视频帧检测")
async def detect_video(
    file: UploadFile = File(..., description="视频文件"),
    model: str = "general",
    confidence: float = 0.3,
    frame_interval: int = 10,
    request: Request = None,
):
    """上传视频逐帧检测，frame_interval 表示每隔多少帧检测一次。"""
    try:
        import tempfile, os

        # Validate frame_interval
        if frame_interval < 1:
            frame_interval = 1
        elif frame_interval > 100:
            frame_interval = 100

        suffix = os.path.splitext(file.filename or "video.mp4")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            # File size limit: 100MB
            if len(content) > 100 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="文件过大，最大支持 100MB")
            tmp.write(content)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            os.unlink(tmp_path)
            raise HTTPException(status_code=400, detail="无法打开视频文件")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        results = []
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % frame_interval == 0:
                detections, inference_time = await detector.detect_with_model(
                    frame, model, confidence_threshold=confidence
                )
                if len(detections) > 0:
                    frame_results = []
                    for i in range(len(detections)):
                        class_id = int(detections.class_id[i])
                        conf = float(detections.confidence[i])
                        bbox = detections.xyxy[i].tolist()
                        class_name = detector.get_class_name(model, class_id)
                        frame_results.append({
                            "class_name": class_name, "confidence": round(conf, 4),
                            "bbox": [round(x, 1) for x in bbox],
                        })
                    results.append({
                        "frame": frame_idx,
                        "time": round(frame_idx / fps, 2),
                        "detections": frame_results,
                    })
            frame_idx += 1

        cap.release()
        os.unlink(tmp_path)

        return {
            "success": True,
            "total_frames": total_frames,
            "analyzed_frames": frame_idx,
            "frame_interval": frame_interval,
            "frames_with_detections": len(results),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("video_detect_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"视频检测失败: {str(e)}")


@router.post("/detect/compare", summary="多模型对比检测")
async def detect_compare(
    file: UploadFile = File(..., description="图片文件"),
    confidence: float = 0.3,
):
    """同一张图片用多个模型检测，返回对比结果。"""
    try:
        img_bytes = await file.read()
        if len(img_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件过大，最大支持 10MB")
        img_array = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            raise HTTPException(status_code=400, detail="无法读取图片")

        models = ["general", "fire_smoke", "helmet"]
        results = {}
        for m in models:
            try:
                detections, inference_time = await detector.detect_with_model(
                    frame, m, confidence_threshold=confidence
                )
                dets = []
                for i in range(len(detections)):
                    class_id = int(detections.class_id[i])
                    conf = float(detections.confidence[i])
                    bbox = detections.xyxy[i].tolist()
                    class_name = detector.get_class_name(m, class_id)
                    dets.append({
                        "class_name": class_name, "confidence": round(conf, 4),
                        "bbox": [round(x, 1) for x in bbox],
                    })
                results[m] = {"detections": dets, "count": len(dets), "time_ms": round(inference_time, 1)}
            except Exception as e:
                results[m] = {"detections": [], "count": 0, "time_ms": 0, "error": str(e)}

        return {"success": True, "results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对比检测失败: {str(e)}")


@router.post("/detect/{result_id}/import-annotations", summary="检测结果导入标注")
async def import_annotations_from_detect(result_id: int, request: Request = None):
    """将检测结果的检测框导入为标注数据。"""
    try:
        from app.db import async_session
        from app.models.detection_result import DetectionResult
        from app.models.detection_box import DetectionBox
        from app.models.annotation_image import AnnotationImage
        from app.models.annotation_box import AnnotationBox
        from sqlalchemy import select

        user = getattr(request.state, "user", {}) if request else {}
        username = user.get("username")

        async with async_session() as session:
            # 获取检测结果
            det = await session.scalar(select(DetectionResult).where(DetectionResult.id == result_id))
            if not det:
                raise HTTPException(status_code=404, detail="检测记录不存在")

            # 获取检测框
            boxes_result = await session.execute(
                select(DetectionBox).where(DetectionBox.result_id == result_id)
            )
            det_boxes = boxes_result.scalars().all()

            if not det_boxes:
                return {"success": False, "message": "无检测框可导入"}

            # 查找或创建标注图片记录
            img_result = await session.execute(
                select(AnnotationImage).where(AnnotationImage.filename == det.filename)
            )
            ann_img = img_result.scalar_one_or_none()
            if not ann_img:
                ann_img = AnnotationImage(
                    filename=det.filename,
                    file_path=det.image_path or "",
                    width=det.image_width,
                    height=det.image_height,
                    dataset_name="from_detect",
                    is_annotated=True,
                    box_count=len(det_boxes),
                    create_by=username,
                )
                session.add(ann_img)
                await session.flush()
            else:
                ann_img.is_annotated = True
                ann_img.box_count = len(det_boxes)
                ann_img.update_by = username

            # 导入检测框为标注框
            await session.execute(
                select(AnnotationBox).where(AnnotationBox.image_id == ann_img.id).delete()
            )
            for db in det_boxes:
                img_w = det.image_width or 1
                img_h = det.image_height or 1
                session.add(AnnotationBox(
                    image_id=ann_img.id,
                    class_id=db.class_id,
                    class_name=db.class_name,
                    cx=(db.bbox_x1 + db.bbox_x2) / 2 / img_w,
                    cy=(db.bbox_y1 + db.bbox_y2) / 2 / img_h,
                    bw=(db.bbox_x2 - db.bbox_x1) / img_w,
                    bh=(db.bbox_y2 - db.bbox_y1) / img_h,
                    confidence=db.confidence,
                    annotator="auto_detect",
                    create_by=username,
                ))

            await session.commit()

        await log_operation("import_annotations", username, f"从检测结果 #{result_id} 导入 {len(det_boxes)} 个标注框", request)
        return {"success": True, "message": f"已导入 {len(det_boxes)} 个标注框", "count": len(det_boxes)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


# ── Stream Health Trends ──

@router.get("/health/trend", summary="流健康度趋势")
async def stream_health_trend(
    stream_id: str = None,
    hours: int = 24,
    limit: int = 200,
):
    """查询指定流在最近 N 小时内的健康度趋势（FPS、状态变化）。"""
    from app.db import async_session
    from app.models.stream_health import StreamHealth
    from sqlalchemy import select, text
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(hours=hours)

    async with async_session() as session:
        stmt = select(StreamHealth).where(StreamHealth.recorded_at >= cutoff)
        if stream_id:
            stmt = stmt.where(StreamHealth.stream_id == stream_id)
        stmt = stmt.order_by(StreamHealth.recorded_at.asc()).limit(limit)
        result = await session.execute(stmt)
        items = [
            {
                "stream_id": r.stream_id,
                "status": r.status,
                "fps": r.fps,
                "error_message": r.error_message,
                "recorded_at": str(r.recorded_at) if r.recorded_at else None,
            }
            for r in result.scalars().all()
        ]

    return {"success": True, "total": len(items), "items": items}


# ── Batch Video Analysis ──

@router.post("/batch/analyze", summary="批量视频分析")
async def batch_analyze_videos(
    directory: str = Form(..., description="视频文件夹路径"),
    model: str = Form("general", description="模型: general/helmet/fire_smoke"),
    confidence: float = Form(0.3, description="置信度阈值"),
    frame_interval: int = Form(10, description="每隔多少帧检测一次"),
    request: Request = None,
):
    """批量分析指定目录下的所有视频文件，返回 JSON 结果。"""
    import os
    from pathlib import Path

    # Path traversal protection
    if '..' in directory or not os.path.isabs(directory):
        raise HTTPException(status_code=400, detail="请使用绝对路径")
    resolved = Path(directory).resolve()
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在: {directory}")

    # Validate frame_interval
    if frame_interval < 1:
        frame_interval = 1
    elif frame_interval > 100:
        frame_interval = 100

    from app.core.batch_analyzer import batch_analyze
    result = await batch_analyze(str(resolved), model, confidence, frame_interval)
    return {"success": True, **result}


@router.post("/batch/report", summary="批量分析HTML报告")
async def batch_analyze_report(
    directory: str = Form(..., description="视频文件夹路径"),
    model: str = Form("general", description="模型: general/helmet/fire_smoke"),
    confidence: float = Form(0.3, description="置信度阈值"),
    frame_interval: int = Form(10, description="每隔多少帧检测一次"),
    request: Request = None,
):
    """批量分析并生成 HTML 报告。"""
    import os
    from pathlib import Path

    # Path traversal protection
    if '..' in directory or not os.path.isabs(directory):
        raise HTTPException(status_code=400, detail="请使用绝对路径")
    resolved = Path(directory).resolve()
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在: {directory}")

    if frame_interval < 1:
        frame_interval = 1
    elif frame_interval > 100:
        frame_interval = 100

    from app.core.batch_analyzer import batch_analyze, generate_html_report
    from fastapi.responses import HTMLResponse

    result = await batch_analyze(directory, model, confidence, frame_interval)
    html = generate_html_report(result)
    return HTMLResponse(content=html)
