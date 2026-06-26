import asyncio
import io
from typing import List, Optional

import cv2
import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field

from app.config import settings
from app.core.detector import detector
from app.core.stream_processor import stream_manager
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/stream", tags=["流处理管理"])


# 请求/响应模型
class StreamStartRequest(BaseModel):
    """启动流处理请求模型"""

    stream_url: str = Field(..., description="监控流地址 (RTSP/RTMP)", examples=["rtsp://admin:password@192.168.1.100:554/stream1"])
    stream_id: str = Field(..., description="流唯一标识符", min_length=1, max_length=64, examples=["camera-001"])
    validate: bool = Field(True, description="是否在启动前验证流可用性")
    alarm_types: List[str] = Field(
        default=["helmet", "fire", "intrusion"],
        description="要检测的告警类型: helmet(安全帽), fire(火灾), intrusion(入侵检测)",
        examples=[["helmet", "fire", "intrusion"]]
    )


class DetectRequest(BaseModel):
    """图片检测请求模型"""
    image_url: str = Field(..., description="图片地址（HTTP/HTTPS URL 或本地路径）")
    model: str = Field("general", description="使用哪个模型: general(通用), helmet(安全帽), fire_smoke(火灾烟雾)")
    confidence: Optional[float] = Field(None, description="置信度阈值（可选，不传则用默认值）")


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


@router.post("/start", response_model=StreamResponse, summary="启动流处理", description="启动对指定监控流的实时YOLO检测处理")
async def start_stream(request: StreamStartRequest):
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
        validate=request.validate,
        alarm_types=request.alarm_types,
    )

    # 启动流处理
    result = await stream_manager.start_stream(
        stream_id=request.stream_id,
        stream_url=request.stream_url,
        validate=request.validate,
        alarm_types=request.alarm_types,
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

    return StreamResponse(
        success=True,
        stream_id=request.stream_id,
        message=result["message"],
    )


@router.post("/stop", response_model=StreamResponse, summary="停止流处理", description="优雅停止指定流的处理并释放资源")
async def stop_stream(request: StreamStopRequest):
    """停止流处理接口。

    优雅停止指定流的处理器并释放相关资源。
    """
    logger.info("api_stop_stream", stream_id=request.stream_id)

    success = await stream_manager.stop_stream(request.stream_id)

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"流 '{request.stream_id}' 未找到",
        )

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


@router.get("/alarms", summary="查询告警列表", description="查询告警记录，支持按流ID和告警类型筛选")
async def get_alarms(
    stream_id: Optional[str] = None,
    alarm_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """查询告警列表接口。

    - **stream_id**: 按流ID筛选（可选）
    - **alarm_type**: 按告警类型筛选（可选）: helmet, animal, fire, intrusion
    - **limit**: 返回记录数（默认100）
    - **offset**: 偏移量（默认0）
    """
    from app.services.database import db_service

    alarms = await db_service.get_alarms(
        stream_id=stream_id,
        alarm_type=alarm_type,
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
async def delete_all_alarms():
    """清空所有告警记录接口。"""
    from app.services.database import db_service

    count = await db_service.delete_all_alarms()

    return {"success": True, "message": f"已删除 {count} 条告警记录"}


# ── 调试接口 ──

from fastapi import UploadFile, File


class DetectRequest(BaseModel):
    image_url: str = Field(..., description="图片地址（支持 HTTP/HTTPS 直链）")
    model: str = Field("general", description="模型名称: general / fire_smoke / helmet")
    confidence: float = Field(0.3, description="置信度阈值", ge=0.0, le=1.0)


class DetectResult(BaseModel):
    class_name: str
    class_id: int
    confidence: float
    bbox: List[float]


@router.post("/detect", summary="图片检测调试", description="传入图片地址（HTTP URL 或本地路径），返回模型识别结果")
async def detect_image(request: DetectRequest):
    """图片检测调试接口。

    传入图片地址（HTTP URL 或本地路径），返回指定模型的识别结果。

    - **image_url**: 图片地址
    - **model**: 使用的模型 (general/helmet/fire_smoke)
    - **confidence**: 置信度阈值（可选）
    """
    try:
        # 下载或读取图片
        if request.image_url.startswith(("http://", "https://")):
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
async def detect_upload(
    file: UploadFile = File(..., description="图片文件"),
    model: str = "general",
    confidence: float = 0.3,
    request: Request = None,
):
    """上传图片检测接口。

    支持 jpg/png/bmp 格式，返回检测框、类别和置信度。检测结果自动存入数据库。
    """
    try:
        # 读取上传的图片
        img_bytes = await file.read()
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
async def detect_history(limit: int = 50, offset: int = 0):
    from app.db import async_session
    from app.models.detection_result import DetectionResult
    from app.models.detection_box import DetectionBox
    from sqlalchemy import select, func

    async with async_session() as session:
        total = await session.scalar(select(func.count(DetectionResult.id)))
        result = await session.execute(
            select(DetectionResult)
            .order_by(DetectionResult.detected_at.desc())
            .limit(limit).offset(offset)
        )
        items = []
        for r in result.scalars().all():
            # 查询该结果的检测类别
            boxes_result = await session.execute(
                select(DetectionBox.class_name, func.count(DetectionBox.id))
                .where(DetectionBox.result_id == r.id)
                .group_by(DetectionBox.class_name)
            )
            class_summary = [f"{cn}({cnt})" for cn, cnt in boxes_result.all()]

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
                "class_summary": class_summary,
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
async def detect_delete_all():
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
