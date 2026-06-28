import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import av
import cv2
import numpy as np
from supervision.tracker.byte_tracker.core import ByteTrack

from app.config import settings
from app.core.alarm_dedup import alarm_dedup
from app.core.detector import detector
from app.services.minio_client import minio_service
from app.services.worker_tasks import enqueue_alarm_task
from app.utils.logger import get_logger, print_status

logger = get_logger(__name__)

# Dedicated thread pool for RTSP frame reading
_stream_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stream")

# Queue size for frame buffering between reader thread and async processor
_FRAME_QUEUE_SIZE = 32


class StreamProcessor:
    """Process a single video stream with dual-strategy slicing."""

    # 告警类型到模型的映射
    ALARM_TYPE_TO_MODELS = {
        "helmet": ["helmet"],           # 安全帽检测使用安全帽模型
        "fire": ["fire_smoke"],         # 火灾检测使用火灾烟雾模型
        "intrusion": ["general"],       # 入侵检测使用通用模型（人、动物）
    }

    def __init__(self, stream_id: str, stream_url: str, alarm_types: List[str] = None,
                 roi: tuple = None):
        self.stream_id = stream_id
        self.stream_url = stream_url
        self.alarm_types = alarm_types or ["helmet", "fire", "intrusion"]
        self._roi = roi  # (x, y, w, h) or None for full frame
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._container = None  # 保持对 container 的引用，用于 stop 时强制关闭
        self._frame_count = 0
        self._fps_counter = 0
        self._fps_start_time = time.time()
        self._current_fps = 0.0
        self._alarm_count = 0

        # ByteTrack per-stream tracker (每个流独立跟踪)
        # 降低阈值以提高跟踪稳定性
        self._tracker = ByteTrack(
            track_activation_threshold=0.1,
            lost_track_buffer=60,
            minimum_matching_threshold=0.6,
        )

        # 根据选择的告警类型确定需要使用的模型
        self._models_to_use = set()
        for alarm_type in self.alarm_types:
            models = self.ALARM_TYPE_TO_MODELS.get(alarm_type, [])
            self._models_to_use.update(models)

        # 状态追踪：running / error / reconnecting
        self._status = "idle"
        self._error_message = ""

        print_status(f"流 {stream_id} 启用检测类型: {', '.join(self.alarm_types)}", "info")

    async def start(self) -> None:
        """Start the stream processing task."""
        if self._running:
            print_status(f"流 {self.stream_id} 已在运行中", "warning")
            return

        self._running = True
        self._status = "running"
        self._task = asyncio.create_task(self._process_loop())
        # 任务结束时自动从 StreamManager 中移除（防止僵尸流）
        self._task.add_done_callback(self._on_task_done)
        print_status(f"开始处理流: {self.stream_id}", "info")

    def _on_task_done(self, task: asyncio.Task) -> None:
        """任务结束回调：自动从 StreamManager 移除已停止/崩溃的流。"""
        try:
            task.result()  # 检查是否有未处理的异常
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("stream_task_error", stream_id=self.stream_id, error=str(e))

        # 从 StreamManager 中移除（延迟执行，避免在回调中修改 dict）
        asyncio.get_running_loop().call_soon(self._remove_from_manager)

    def _remove_from_manager(self) -> None:
        """从 StreamManager 中移除自身。"""
        if self.stream_id in stream_manager._streams:
            del stream_manager._streams[self.stream_id]
            print_status(f"流 {self.stream_id} 已从管理器中移除", "info")

    async def stop(self) -> None:
        """Stop the stream processing task."""
        self._running = False
        self._status = "stopped"

        # 强制关闭 container，打断阻塞的 decode 调用
        container = self._container
        self._container = None
        if container is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(_stream_executor, container.close)
            except Exception:
                pass

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print_status(f"停止处理流: {self.stream_id}", "info")

    def get_info(self) -> dict:
        """返回流的摘要信息，用于 API 响应。"""
        return {
            "stream_id": self.stream_id,
            "alarm_types": self.alarm_types,
            "status": self._status,
            "error_message": self._error_message,
            "fps": self._current_fps,
            "alarm_count": self._alarm_count,
        }

    async def _process_loop(self) -> None:
        """Main processing loop with reconnection logic."""
        retry_delay = 1.0
        max_retry_delay = 30.0
        max_consecutive_failures = 5
        consecutive_failures = 0

        while self._running:
            try:
                await self._process_stream()
                # 正常结束（流关闭）→ 退出循环
                break
            except asyncio.TimeoutError:
                self._status = "reconnecting"
                self._error_message = "帧接收超时，流可能已断开"
                print_status(f"流 {self.stream_id} 帧接收超时，重连...", "warning")
                consecutive_failures += 1
            except asyncio.CancelledError:
                print_status(f"流 {self.stream_id} 已取消", "info")
                break
            except ConnectionError as e:
                consecutive_failures += 1
                self._status = "reconnecting"
                self._error_message = str(e)
                print_status(f"流 {self.stream_id} 连接失败: {e}", "error")
            except Exception as e:
                consecutive_failures += 1
                self._status = "reconnecting"
                self._error_message = str(e)
                print_status(f"流 {self.stream_id} 错误: {str(e)}", "error")
                logger.error(
                    "stream_error",
                    stream_id=self.stream_id,
                    error=str(e),
                    consecutive_failures=consecutive_failures,
                )

            if consecutive_failures >= max_consecutive_failures:
                self._status = "error"
                self._error_message = f"连续失败 {consecutive_failures} 次"
                print_status(f"流 {self.stream_id} 连续失败 {consecutive_failures} 次，标记为离线", "error")
                break

            if self._running:
                self._status = "reconnecting"
                print_status(f"流 {self.stream_id} {retry_delay}秒后重连...", "warning")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def _process_stream(self) -> None:
        """Process stream frames with dual-strategy slicing."""
        loop = asyncio.get_running_loop()
        logger.info("stream_opening", stream_id=self.stream_id, url=self.stream_url)

        # Open stream with PyAV（带超时保护）
        def open_container():
            container = av.open(
                self.stream_url,
                options={
                    "rtsp_transport": "tcp",
                    "stimeout": "5000000",  # 5 seconds timeout
                    "timeout": "5000000",    # 通用超时（覆盖 HTTP 等协议）
                    "rw_timeout": "10000000",  # 读写超时 10 秒，检测流卡住
                },
            )
            return container

        try:
            container = await asyncio.wait_for(
                loop.run_in_executor(_stream_executor, open_container),
                timeout=15,
            )
        except asyncio.TimeoutError:
            raise ConnectionError(f"打开流超时 (15秒): {self.stream_url}")

        self._container = container
        logger.info("stream_opened", stream_id=self.stream_id)

        # Use a separate thread to read frames into a queue,
        # avoiding thread pool contention with async event loop.
        frame_queue: asyncio.Queue = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
        decode_error = [None]

        def _reader_thread():
            """Run in a dedicated thread: decode frames and put into queue."""
            try:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                count = 0
                for frame in container.decode(video=0):
                    if not self._running:
                        break
                    try:
                        frame_queue.put_nowait(frame)
                        count += 1
                        if count <= 3:
                            logger.info("frame_queued", stream_id=self.stream_id, count=count)
                    except asyncio.QueueFull:
                        pass  # Drop frame if queue is full (consumer too slow)
            except Exception as e:
                decode_error[0] = e
                logger.error("reader_thread_error", stream_id=self.stream_id, error=repr(e), error_type=type(e).__name__)
            finally:
                # Sentinel to signal end of stream
                try:
                    frame_queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass

        reader_thread = threading.Thread(target=_reader_thread, daemon=True)
        reader_thread.start()

        try:
            last_sample_time = 0
            prev_frame_gray = None
            scene_threshold = 27.0
            frame_count = 0
            frame_timeout = 30

            while self._running:
                try:
                    frame = await asyncio.wait_for(frame_queue.get(), timeout=frame_timeout)
                except asyncio.TimeoutError:
                    logger.warning("frame_queue_timeout", stream_id=self.stream_id)
                    break

                if frame is None:
                    break

                frame_count += 1
                if frame_count == 1:
                    logger.info("first_frame_received", stream_id=self.stream_id)
                elif frame_count % 100 == 0:
                    logger.debug("frame_progress", stream_id=self.stream_id, frames=frame_count)

                current_time = time.time()
                img = frame.to_ndarray(format="bgr24")

                # 去隔行：检测并消除隔行扫描伪影（残影）
                try:
                    is_interlaced = getattr(frame, 'interlaced', False)
                    if is_interlaced:
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        # YADIF 风格去隔行：奇偶行分离后混合
                        top = gray[0::2, :]
                        bottom = gray[1::2, :]
                        if top.shape[0] == bottom.shape[0]:
                            blended = ((top.astype(np.uint16) + bottom.astype(np.uint16)) // 2).astype(np.uint8)
                            img = cv2.cvtColor(blended, cv2.COLOR_GRAY2BGR)
                except Exception:
                    pass

                # Strategy 1: Fixed time sampling (every 1 second)
                should_process = (current_time - last_sample_time) >= (1.0 / 1.0)

                # Strategy 2: Scene change detection using frame difference
                if not should_process and prev_frame_gray is not None:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    diff = cv2.absdiff(prev_frame_gray, gray)
                    score = np.mean(diff)
                    del diff
                    if score > scene_threshold:
                        should_process = True
                        logger.debug("scene_change_detected", stream_id=self.stream_id, score=round(float(score), 2))
                    prev_frame_gray = gray
                elif prev_frame_gray is None:
                    prev_frame_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

                if should_process:
                    last_sample_time = current_time
                    await self._process_frame(img)
                    if frame_count <= 3:
                        logger.info("frame_processed", stream_id=self.stream_id, frame_num=frame_count)

                self._fps_counter += 1
                if current_time - self._fps_start_time >= 1.0:
                    self._current_fps = self._fps_counter
                    self._fps_counter = 0
                    self._fps_start_time = current_time

                del img

        finally:
            prev_frame_gray = None
            # Drain remaining frames in queue
            while not frame_queue.empty():
                try:
                    frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            reader_thread.join(timeout=3)
            if self._container is not None:
                self._container = None
                try:
                    container.close()
                except Exception:
                    pass

    # 告警类型对应的颜色 (BGR格式)
    ALARM_COLORS = {
        "helmet": (0, 255, 0),      # 绿色
        "no-helmet": (0, 0, 255),   # 红色
        "animal": (255, 165, 0),    # 橙色
        "fire": (0, 0, 255),        # 红色
        "smoke": (128, 128, 128),   # 灰色
        "intrusion": (0, 165, 255), # 橙色
    }

    async def _process_frame(self, frame: np.ndarray) -> None:
        """Process a single frame: detect with selected models, draw boxes, and trigger alarms."""
        annotated_frame = None
        try:
            annotated_frame = frame.copy()
            alarm_detections = []

            # Apply ROI crop if configured
            detect_frame = frame
            roi_offset = (0, 0)
            if self._roi:
                rx, ry, rw, rh = self._roi
                h, w = frame.shape[:2]
                rx = max(0, min(rx, w))
                ry = max(0, min(ry, h))
                rw = min(rw, w - rx)
                rh = min(rh, h - ry)
                if rw > 0 and rh > 0:
                    detect_frame = frame[ry:ry+rh, rx:rx+rw]
                    roi_offset = (rx, ry)

            # 只使用用户选择的模型进行检测
            for model_name in self._models_to_use:
                try:
                    detections, inference_time = await detector.detect_with_model(
                        detect_frame, model_name, tracker=self._tracker
                    )
                    from app.core.metrics import observe_histogram
                    observe_histogram("argus_inference_ms", inference_time / 1000.0, model=model_name)
                    logger.debug("detection_result", stream_id=self.stream_id, model=model_name,
                                 count=len(detections), time_ms=round(inference_time, 1),
                                 conf_threshold=settings.CONFIDENCE_THRESHOLD)
                except Exception as e:
                    logger.error(f"detection_error_{model_name}", error=str(e))
                    continue

                if len(detections) == 0:
                    continue

                for i in range(len(detections)):
                    class_id = detections.class_id[i]
                    confidence = detections.confidence[i]
                    track_id = int(detections.tracker_id[i]) if detections.tracker_id is not None else -1
                    bbox = detections.xyxy[i]

                    # Offset back to original frame coordinates if ROI was applied
                    ox, oy = roi_offset
                    bbox = bbox.copy()
                    bbox[0] += ox
                    bbox[1] += oy
                    bbox[2] += ox
                    bbox[3] += oy

                    class_name = detector.get_class_name(model_name, class_id)
                    alarm_type = self._get_alarm_type(model_name, class_name)
                    if alarm_type is None or alarm_type not in self.alarm_types:
                        continue

                    # 计算中心位置用于去重
                    cx = int((bbox[0] + bbox[2]) / 2)
                    cy = int((bbox[1] + bbox[3]) / 2)

                    x1, y1, x2, y2 = map(int, bbox)
                    h, w = frame.shape[:2]
                    x1 = max(0, min(x1, w))
                    y1 = max(0, min(y1, h))
                    x2 = max(0, min(x2, w))
                    y2 = max(0, min(y2, h))

                    if x2 <= x1 or y2 <= y1:
                        continue

                    # 检查人体是否大部分进入画面
                    bbox_w = x2 - x1
                    bbox_h = y2 - y1
                    bbox_area = bbox_w * bbox_h
                    frame_area = w * h
                    area_ratio = bbox_area / frame_area

                    # 人体高度应大于宽度（站立姿态），且面积占画面一定比例
                    if class_name == "person":
                        is_standing = bbox_h > bbox_w * 0.5
                        is_large_enough = area_ratio >= 0.08  # 至少占画面 8%
                        if not is_standing or not is_large_enough:
                            continue

                    # 画框（所有检测到的目标都画，不受告警去重影响）
                    confidence_value = float(confidence)
                    color = self.ALARM_COLORS.get(alarm_type, (0, 255, 0))
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)

                    label = f"{class_name} {confidence_value:.1%}"

                    (label_w, label_h), baseline = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                    )
                    cv2.rectangle(annotated_frame, (x1, y1 - label_h - 10), (x1 + label_w, y1), color, -1)
                    cv2.putText(annotated_frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                    # 告警去重（只控制是否发送告警，不影响画框）
                    should_alarm = await alarm_dedup.should_trigger_alarm(
                        self.stream_id, class_name, track_id, position=(cx, cy)
                    )

                    if should_alarm:
                        try:
                            alarm_detections.append({
                                "alarm_type": alarm_type,
                                "class_name": class_name,
                                "confidence": confidence_value,
                                "track_id": track_id,
                            })
                            self._alarm_count += 1

                            print_status(
                                f"[ALARM] [{self.stream_id}] {model_name}: {class_name} conf={confidence_value:.1%}",
                                "warning"
                            )
                        except Exception as e:
                            logger.error("alarm_box_error", stream_id=self.stream_id, error=str(e))

            # 如果有告警，编码上传并入库（后台执行，不阻塞帧循环）
            if alarm_detections:
                asyncio.create_task(self._save_alarm(annotated_frame, alarm_detections))

        except Exception as e:
            logger.error(
                "frame_processing_error",
                stream_id=self.stream_id,
                error=str(e),
            )
        finally:
            # 确保标注帧在任何情况下都被释放
            annotated_frame = None

    async def _save_alarm(self, annotated_frame: np.ndarray, alarm_detections: list) -> None:
        """Save alarm: encode image, upload to MinIO, enqueue to ARQ."""
        try:
            if annotated_frame is None:
                logger.error("save_alarm_no_frame", stream_id=self.stream_id)
                return

            # 轻度锐化：过强会放大隔行伪影和噪点
            blurred = cv2.GaussianBlur(annotated_frame, (0, 0), 2)
            sharpened = cv2.addWeighted(annotated_frame, 1.2, blurred, -0.2, 0)

            # Use PNG for lossless quality
            success, img_encoded = cv2.imencode(".png", sharpened)
            del sharpened

            if not success or img_encoded is None:
                logger.error("jpeg_encode_failed", stream_id=self.stream_id)
                return

            image_bytes = img_encoded.tobytes()
            del img_encoded

            object_key = await minio_service.upload_image(image_bytes, self.stream_id, content_type="image/png")
            del image_bytes

            if object_key:
                logger.info("annotated_image_uploaded", stream_id=self.stream_id, object_key=object_key)
            else:
                logger.warning("minio_upload_failed_no_image", stream_id=self.stream_id)

            # Compute severity based on recent alarm frequency
            from app.core.alarm_severity import compute_severity
            severity_counts = {}
            for alarm in alarm_detections:
                at = alarm["alarm_type"]
                if at not in severity_counts:
                    severity_counts[at] = await compute_severity(self.stream_id, at)

            for alarm in alarm_detections:
                severity = severity_counts.get(alarm["alarm_type"], "normal")
                await enqueue_alarm_task(
                    stream_url=self.stream_url,
                    stream_id=self.stream_id,
                    alarm_type=alarm["alarm_type"],
                    confidence=alarm["confidence"],
                    minio_key=object_key or "",
                    track_id=alarm["track_id"],
                    class_name=alarm.get("class_name", ""),
                    severity=severity,
                )
                # Broadcast to WebSocket clients
                from app.core.alarm_broadcaster import alarm_broadcaster
                await alarm_broadcaster.broadcast({
                    "type": "alarm",
                    "stream_id": self.stream_id,
                    "alarm_type": alarm["alarm_type"],
                    "class_name": alarm.get("class_name", ""),
                    "confidence": alarm["confidence"],
                    "severity": severity,
                    "image_key": object_key or "",
                })
                # Update metrics
                from app.core.metrics import inc_counter
                inc_counter("argus_alarms_total", alarm_type=alarm["alarm_type"], severity=severity)
        except Exception as e:
            logger.error("alarm_save_error", stream_id=self.stream_id, error=str(e))

    def _get_alarm_type(self, model_name: str, class_name: str) -> Optional[str]:
        """将模型检测结果映射到用户选择的告警类型。

        Returns:
            告警类型 (helmet/animal/fire) 或 None (如果不匹配)
        """
        # 安全帽模型检测结果
        if model_name == "helmet":
            if class_name in ["helmet", "no-helmet"]:
                return "helmet"
            return None

        # 火灾烟雾模型检测结果
        if model_name == "fire_smoke":
            if class_name in ("fire", "smoke"):
                return "fire"
            return None

        # 通用模型检测结果（人、动物）
        if model_name == "general":
            if class_name == "person":
                return "intrusion"
            animal_classes = ["bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"]
            if class_name in animal_classes:
                return "intrusion"
            return None

        return None


class StreamManager:
    """Singleton manager for multiple stream processors."""

    _instance: Optional["StreamManager"] = None

    def __new__(cls) -> "StreamManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._streams = {}
            cls._instance._validation_threads = set()  # 追踪验证线程
        return cls._instance

    @property
    def active_streams(self) -> int:
        """Get the number of active streams."""
        return len(self._streams)

    @property
    def stream_ids(self) -> list:
        """Get list of active stream IDs."""
        return list(self._streams.keys())

    def get_streams_info(self) -> list:
        """获取所有活跃流的详细信息列表。"""
        return [proc.get_info() for proc in self._streams.values()]

    async def _validate_stream(self, stream_url: str, timeout: int = 15) -> tuple[bool, str]:
        """Validate if a stream URL is accessible and can produce frames.

        两层超时保护：
        - asyncio.wait_for: 外层异步超时，确保整个验证不会阻塞事件循环
        - thread.join: 内层线程超时 + container.close() 强制中断

        Returns:
            Tuple of (is_valid, message)
        """
        loop = asyncio.get_running_loop()

        def _try_open():
            result = [False, "验证超时"]
            container_ref = [None]

            def _connect():
                try:
                    container = av.open(
                        stream_url,
                        options={
                            "rtsp_transport": "tcp",
                            "stimeout": "5000000",
                            "timeout": "5000000",      # 通用超时（覆盖 HTTP 等协议）
                            "rtsp_flags": "prefer_tcp",
                            "analyzeduration": "1000000",
                            "probesize": "1000000",
                        },
                    )
                    container_ref[0] = container

                    if not container.streams.video:
                        result[0] = False
                        result[1] = "没有找到视频流"
                        return

                    frame_count = 0
                    for frame in container.decode(video=0):
                        frame_count += 1
                        if frame_count >= 1:
                            break

                    if frame_count > 0:
                        result[0] = True
                        result[1] = "流验证成功"
                    else:
                        result[0] = False
                        result[1] = "无法解码视频帧"

                except av.FFmpegError as e:
                    result[0] = False
                    result[1] = f"流连接失败: {str(e)[:100]}"
                except Exception as e:
                    result[0] = False
                    result[1] = f"验证失败: {str(e)[:100]}"
                finally:
                    if container_ref[0]:
                        try:
                            container_ref[0].close()
                        except Exception:
                            pass
                        container_ref[0] = None

            thread = threading.Thread(target=_connect, daemon=True)
            self._validation_threads.add(thread)
            thread.start()
            # 内层超时：给 10 秒，留 5 秒给外层 asyncio.wait_for 兜底
            thread.join(timeout=min(timeout - 2, 10))
            self._validation_threads.discard(thread)

            if thread.is_alive():
                if container_ref[0]:
                    try:
                        container_ref[0].close()
                    except Exception:
                        pass
                    container_ref[0] = None
                return False, f"连接超时 ({timeout}秒)"

            return result[0], result[1]

        try:
            is_valid, message = await asyncio.wait_for(
                loop.run_in_executor(_stream_executor, _try_open),
                timeout=timeout,
            )
            return is_valid, message
        except asyncio.TimeoutError:
            return False, f"连接超时 ({timeout}秒)"

    async def start_stream(self, stream_id: str, stream_url: str, validate: bool = True,
                           alarm_types: List[str] = None, roi: tuple = None) -> dict:
        """Start processing a stream with optional validation.

        Args:
            stream_id: 流唯一标识符
            stream_url: 流地址
            validate: 是否验证流可用性
            alarm_types: 要检测的告警类型列表 ["helmet", "animal", "fire", "intrusion"]
            roi: Region of Interest (x, y, w, h) in pixels, or None for full frame

        Returns:
            Dict with status and message.
        """
        if alarm_types is None:
            alarm_types = ["helmet", "fire", "intrusion"]

        if stream_id in self._streams:
            return {"success": False, "message": f"流 {stream_id} 已存在"}

        if self.active_streams >= settings.MAX_CONCURRENT_STREAMS:
            return {"success": False, "message": f"已达最大并发流数量 ({settings.MAX_CONCURRENT_STREAMS})"}

        # Validate stream before starting
        if validate:
            print_status(f"正在验证流: {stream_id}...", "info")
            is_valid, message = await self._validate_stream(stream_url)

            if not is_valid:
                print_status(f"[FAIL] 流验证失败: {message}", "error")
                return {"success": False, "message": f"流验证失败: {message}"}

            print_status(f"[OK] 流验证通过: {message}", "success")

        processor = StreamProcessor(stream_id, stream_url, alarm_types, roi=roi)
        self._streams[stream_id] = processor
        await processor.start()

        print_status(f"[OK] 流 {stream_id} 已启动 (当前活跃: {self.active_streams})", "success")
        return {"success": True, "message": "流已启动"}

    async def stop_stream(self, stream_id: str) -> bool:
        """Stop processing a stream.

        Returns:
            True if stopped, False if not found.
        """
        processor = self._streams.pop(stream_id, None)
        if not processor:
            print_status(f"流 {stream_id} 未找到", "warning")
            return False

        await processor.stop()

        print_status(f"[OK] 流 {stream_id} 已停止 (当前活跃: {self.active_streams})", "success")
        return True

    async def stop_all(self) -> None:
        """Stop all streams, join lingering validation threads, and reset state."""
        for stream_id in list(self._streams.keys()):
            await self.stop_stream(stream_id)
        self._streams.clear()

        # 等待残留的验证线程结束（最多 5 秒）
        for thread in list(self._validation_threads):
            thread.join(timeout=5)
        self._validation_threads.clear()

        print_status("所有流已停止", "info")


# Singleton instance
stream_manager = StreamManager()
