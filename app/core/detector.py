import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import onnxruntime as ort

import supervision as sv
from supervision.tracker.byte_tracker.core import ByteTrack

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Dedicated thread pool for ONNX inference (avoids blocking default executor)
# Dynamic sizing based on CPU cores
_inference_executor = ThreadPoolExecutor(
    max_workers=min(8, (lambda: __import__('os').cpu_count() or 4)()),
    thread_name_prefix="inference"
)


class ModelSession:
    """ONNX Runtime session wrapper for a single model."""

    def __init__(self, model_path: str, model_name: str):
        self.model_path = model_path
        self.model_name = model_name
        self.session: Optional[ort.InferenceSession] = None
        self.input_shape: Tuple[int, int] = (640, 640)

    def get_session(self) -> ort.InferenceSession:
        """Get or create ONNX Runtime session."""
        if self.session is None:
            import os
            import sys

            # 抑制 ONNX Runtime C++ 层的红色报错，改用中文提示
            os.environ["ONNXRUNTIME_LOG_LEVEL"] = "3"  # 仅 ERROR

            # 强制使用 CPU（GTX 1080 + cuDNN 9 不兼容）
            providers_to_try = ["CPUExecutionProvider"]

            for provider in providers_to_try:
                try:
                    # 临时重定向 stderr 避免 C++ 错误刷屏
                    old_stderr = sys.stderr
                    devnull = open(os.devnull, 'w')
                    sys.stderr = devnull
                    try:
                        sess = ort.InferenceSession(
                            self.model_path,
                            providers=[provider],
                        )
                    finally:
                        sys.stderr = old_stderr
                        devnull.close()

                    input_meta = sess.get_inputs()[0]
                    self.input_shape = (input_meta.shape[2], input_meta.shape[3])

                    actual = sess.get_providers()
                    used_provider = "CPUExecutionProvider"

                    dummy = np.random.randn(1, 3, self.input_shape[0], self.input_shape[1]).astype(np.float32)

                    old_stderr = sys.stderr
                    devnull = open(os.devnull, 'w')
                    sys.stderr = devnull
                    try:
                        sess.run(None, {input_meta.name: dummy})
                    finally:
                        sys.stderr = old_stderr
                        devnull.close()

                    self.session = sess
                    logger.info("cpu_ready", model=self.model_name)
                    break

                except Exception:
                    if provider == "CPUExecutionProvider":
                        raise

        return self.session

    def close(self) -> None:
        """Release ONNX session resources."""
        if self.session is not None:
            del self.session
            self.session = None


class MultiModelDetector:
    """Multi-model YOLO detector with ByteTrack post-processing."""

    def __init__(self):
        self._models: Dict[str, ModelSession] = {
            "general": ModelSession(settings.YOLO_ONNX_PATH, "通用模型"),
            "fire_smoke": ModelSession(settings.FIRE_SMOKE_MODEL_PATH, "火灾烟雾模型"),
            "helmet": ModelSession(settings.HELMET_MODEL_PATH, "安全帽模型"),
        }
        # 安全帽检测专用轻量模型
        self._helmet_person_model = ModelSession(settings.HELMET_PERSON_MODEL_PATH, "安全帽-人检测(Nano)")
        self._helmet_fp16_model = ModelSession(settings.HELMET_FP16_MODEL_PATH, "安全帽模型(FP16)")
        self._class_mapping: Dict[str, Dict[str, str]] = {
            "general": settings.CLASS_MAPPING,
            "fire_smoke": settings.FIRE_SMOKE_CLASS_MAPPING,
            "helmet": settings.HELMET_CLASS_MAPPING,
        }

    def close(self) -> None:
        """Release all ONNX sessions and GPU memory."""
        for model in self._models.values():
            model.close()
        self._helmet_person_model.close()
        self._helmet_fp16_model.close()
        logger.info("detector_sessions_closed")

    def warmup(self) -> None:
        """预热所有模型：加载到内存并运行一次推理，避免首次推理延迟。"""
        import numpy as np
        for name, model in self._models.items():
            try:
                session = model.get_session()
                # 创建 640x640 假帧
                dummy = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
                blob, _ = self._preprocess(dummy, model.input_shape, name)
                input_name = session.get_inputs()[0].name
                session.run(None, {input_name: blob})
                logger.info("model_warmup_ok", model=name)
            except Exception as e:
                logger.warning("model_warmup_failed", model=name, error=str(e))

    def _preprocess(self, frame: np.ndarray, input_shape: Tuple[int, int], model_name: str = "") -> Tuple[np.ndarray, Tuple[float, float]]:
        """Preprocess frame for YOLO inference.

        Returns:
            Preprocessed blob and scale factors (sx, sy)
        """
        h, w = frame.shape[:2]
        target_h, target_w = input_shape

        # Calculate scale
        sx = w / target_w
        sy = h / target_h

        # Resize
        img = cv2.resize(frame, (target_w, target_h))

        # fire_smoke_v2 模型期望 0-255 输入，其他模型归一化到 0-1
        if model_name != "fire_smoke":
            img = img.astype(np.float32) / 255.0
        else:
            img = img.astype(np.float32)

        # HWC to CHW
        img = img.transpose(2, 0, 1)

        # Add batch dimension
        blob = np.expand_dims(img, axis=0)

        return blob, (sx, sy)

    # ONNX Runtime 输出的置信度比 PyTorch 低约 3.7 倍，需要补偿
    ONNX_CONFIDENCE_SCALE: Dict[str, float] = {
        "general": 1.0,
        "fire_smoke": 3.7,
        "helmet": 2.0,
    }

    def _postprocess(
        self,
        output: np.ndarray,
        scale: Tuple[float, float],
        confidence_threshold: float,
        num_classes: int = 80,
        model_name: str = "",
    ) -> sv.Detections:
        """Post-process YOLO output to supervision Detections.

        Supports both detection and segmentation model outputs:
        - Detection: [cx, cy, w, h, class0_score, ..., classN_score]
        - Segmentation: [cx, cy, w, h, class0_score, ..., classN_score, mask0, ..., mask31]
        """
        raw = output[0]

        if raw.size == 0 or raw.shape[0] == 0:
            return sv.Detections.empty()

        # Auto-detect transposed format: [C, N] where C > 6 and C << N
        if raw.ndim == 2 and raw.shape[1] > 6 and raw.shape[0] < raw.shape[1]:
            raw = raw.T

        num_cols = raw.shape[1]

        # 区分两种 6 列格式：
        # [x1,y1,x2,y2,conf,class_id] → class_id 列是离散整数 (0,1,2...)
        # [cx,cy,w,h,score0,score1]   → 最后一列是连续浮点 (0.0~1.0)
        if num_cols == 6:
            col5 = raw[:, 5]
            is_class_id_format = (
                len(col5) > 0
                and np.all(col5 == col5.astype(int))
                and col5.max() <= 10
                and col5.min() >= 0
            )
        else:
            is_class_id_format = False

        if is_class_id_format:
            # Format: [x1, y1, x2, y2, conf, class_id]
            boxes = raw[:, :4]
            scores = raw[:, 4]
            class_ids = raw[:, 5].astype(int)
        elif num_cols >= 5:
            # Format: [cx, cy, w, h, class_scores...]
            cx = raw[:, 0]
            cy = raw[:, 1]
            w = raw[:, 2]
            h = raw[:, 3]
            boxes = np.column_stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])

            class_scores = raw[:, 4:4 + num_classes]

            if class_scores.max() > 1.0:
                class_scores = 1.0 / (1.0 + np.exp(-class_scores))

            scores = class_scores.max(axis=1)
            class_ids = class_scores.argmax(axis=1).astype(int)
        else:
            return sv.Detections.empty()

        # ONNX 置信度补偿：ONNX Runtime 输出比 PyTorch 低约 N 倍
        conf_scale = self.ONNX_CONFIDENCE_SCALE.get(model_name, 1.0)
        if conf_scale != 1.0:
            scores = np.clip(scores * conf_scale, 0.0, 1.0)

        # Filter by confidence
        conf_mask = scores >= confidence_threshold
        boxes = boxes[conf_mask]
        scores = scores[conf_mask]
        class_ids = class_ids[conf_mask]

        if len(boxes) == 0:
            return sv.Detections.empty()

        # Scale boxes back to original image size
        sx, sy = scale
        boxes = boxes.copy()
        boxes[:, [0, 2]] *= sx
        boxes[:, [1, 3]] *= sy

        dets = sv.Detections(
            xyxy=boxes,
            confidence=scores,
            class_id=class_ids,
        )

        # Apply NMS to remove overlapping detections
        if len(dets) > 1:
            dets = dets.with_nms(threshold=settings.NMS_THRESHOLD)

        return dets

    async def detect_with_model(
        self,
        frame: np.ndarray,
        model_name: str,
        confidence_threshold: Optional[float] = None,
        tracker: Optional[ByteTrack] = None,
    ) -> Tuple[sv.Detections, float]:
        """Run detection with a specific model.

        Args:
            frame: BGR image as numpy array
            model_name: Model to use ("general", "fire_smoke", "helmet")
            confidence_threshold: Override default confidence threshold
            tracker: Optional ByteTrack instance for object tracking

        Returns:
            Tuple of (Detections, inference time in ms)
        """
        if confidence_threshold is None:
            if model_name == "fire_smoke":
                confidence_threshold = settings.FIRE_SMOKE_CONFIDENCE_THRESHOLD
            elif model_name == "helmet":
                confidence_threshold = settings.HELMET_CONFIDENCE_THRESHOLD
            else:
                confidence_threshold = settings.CONFIDENCE_THRESHOLD

        model = self._models.get(model_name)
        if model is None:
            raise ValueError(f"Unknown model: {model_name}")

        session = model.get_session()

        # Run in thread pool to avoid blocking
        loop = asyncio.get_running_loop()

        def _run_inference():
            nonlocal session
            # Preprocess
            blob, scale = self._preprocess(frame, model.input_shape, model_name)

            # Get input name
            input_name = session.get_inputs()[0].name

            # Run inference
            start_time = time.time()
            outputs = session.run(None, {input_name: blob})
            inference_time = (time.time() - start_time) * 1000  # ms

            # Get number of classes from model output
            num_classes = outputs[0].shape[1] - 4 if outputs[0].ndim == 3 else outputs[0].shape[1] - 4

            # Post-process
            detections = self._postprocess(outputs[0], scale, confidence_threshold, num_classes, model_name)

            return detections, inference_time

        detections, inference_time = await loop.run_in_executor(_inference_executor, _run_inference)

        # Apply ByteTrack tracking if tracker provided and detections exist
        if tracker is not None and len(detections) > 0:
            # ByteTrack internally filters low-confidence detections.
            # Temporarily boost confidence for tracking, then restore originals.
            orig_conf = detections.confidence.copy()
            boosted = detections.confidence.copy()
            boosted[boosted < 0.5] = 0.5
            detections.confidence = boosted
            tracked = tracker.update_with_detections(detections)
            # Restore original confidence and assign tracker IDs
            detections.confidence = orig_conf
            if len(tracked) > 0 and tracked.tracker_id is not None:
                # Match tracked results back by xyxy coordinates
                tracker_ids = np.full(len(detections), -1, dtype=int)
                for ti in range(len(tracked)):
                    # Find matching detection by comparing boxes
                    diffs = np.abs(detections.xyxy - tracked.xyxy[ti]).sum(axis=1)
                    match_idx = np.argmin(diffs)
                    if diffs[match_idx] < 1.0:
                        tracker_ids[match_idx] = int(tracked.tracker_id[ti])
                detections.tracker_id = tracker_ids

        return detections, inference_time

    async def detect_person_lightweight(
        self,
        frame: np.ndarray,
        confidence_threshold: float = 0.3,
    ) -> Tuple[sv.Detections, float]:
        """用 Nano 模型快速检测人（安全帽检测专用，速度提升 5-10 倍）。"""
        model = self._helmet_person_model
        session = model.get_session()
        loop = asyncio.get_running_loop()

        def _run():
            blob, scale = self._preprocess(frame, model.input_shape, "general")
            input_name = session.get_inputs()[0].name
            start = time.time()
            outputs = session.run(None, {input_name: blob})
            inf_time = (time.time() - start) * 1000
            num_classes = outputs[0].shape[1] - 4
            return self._postprocess(outputs[0], scale, confidence_threshold, num_classes, "general"), inf_time

        return await loop.run_in_executor(_inference_executor, _run)

    async def detect_helmet_lightweight(
        self,
        frame: np.ndarray,
        confidence_threshold: float = 0.01,
    ) -> Tuple[sv.Detections, float]:
        """用 FP16 模型快速检测安全帽（速度提升约 2 倍）。"""
        model = self._helmet_fp16_model
        session = model.get_session()
        loop = asyncio.get_running_loop()

        def _run():
            blob, scale = self._preprocess(frame, model.input_shape, "helmet")
            input_name = session.get_inputs()[0].name
            start = time.time()
            outputs = session.run(None, {input_name: blob})
            inf_time = (time.time() - start) * 1000
            num_classes = outputs[0].shape[1] - 4
            return self._postprocess(outputs[0], scale, confidence_threshold, num_classes, "helmet"), inf_time

        return await loop.run_in_executor(_inference_executor, _run)

    async def detect_helmet_combined(
        self,
        frame: np.ndarray,
        person_threshold: float = 0.3,
        helmet_threshold: float = 0.01,
    ) -> dict:
        """安全帽检测：通用模型检测人 + 安全帽模型检测帽子，差集 = 没戴帽。

        Returns:
            {
                "person_boxes": [(x1, y1, x2, y2, conf), ...],
                "helmet_boxes": [(x1, y1, x2, y2, conf), ...],
                "matched": [{"person": tuple, "helmet": tuple}, ...],
                "no_helmet": [{"person": tuple}, ...],
                "inference_ms": float,
            }
        """
        import asyncio

        img_h, img_w = frame.shape[:2]

        # 先跑通用模型检测人
        person_dets, t1 = await self.detect_with_model(frame, "general", confidence_threshold=person_threshold)

        # 提取 person 框
        person_boxes = []
        for i in range(len(person_dets)):
            cid = int(person_dets.class_id[i])
            cname = self.get_class_name("general", cid)
            if cname != "person":
                continue
            conf = float(person_dets.confidence[i])
            x1, y1, x2, y2 = map(int, person_dets.xyxy[i].tolist())
            x1 = max(0, min(x1, img_w)); y1 = max(0, min(y1, img_h))
            x2 = max(0, min(x2, img_w)); y2 = max(0, min(y2, img_h))
            if x2 <= x1 or y2 <= y1:
                continue
            if (x2 - x1) * (y2 - y1) / (img_w * img_h) < 0.02:
                continue
            person_boxes.append((x1, y1, x2, y2, conf))

        # 没检测到人，跳过安全帽模型
        if not person_boxes:
            return {
                "person_boxes": [],
                "helmet_boxes": [],
                "matched": [],
                "no_helmet": [],
                "inference_ms": t1,
            }

        # 有人才跑安全帽模型
        helmet_dets, t2 = await self.detect_with_model(frame, "helmet", confidence_threshold=helmet_threshold)

        helmet_thresh = settings.HELMET_CONFIRM_THRESHOLD
        helmet_boxes = []
        for i in range(len(helmet_dets)):
            cid = int(helmet_dets.class_id[i])
            cname = self.get_class_name("helmet", cid)
            if cname != "helmet":
                continue
            conf = float(helmet_dets.confidence[i])
            if conf < helmet_thresh:
                continue
            x1, y1, x2, y2 = map(int, helmet_dets.xyxy[i].tolist())
            x1 = max(0, min(x1, img_w)); y1 = max(0, min(y1, img_h))
            x2 = max(0, min(x2, img_w)); y2 = max(0, min(y2, img_h))
            if x2 <= x1 or y2 <= y1:
                continue
            helmet_boxes.append((x1, y1, x2, y2, conf))

        # 一对一贪心匹配
        matched_helmets = set()
        person_helmet_map = {}
        head_not_visible = []
        for pi, (px1, py1, px2, py2, pconf) in enumerate(person_boxes):
            # 头部区域 = 人体框上方 40%
            head_top = py1
            head_bottom = py1 + (py2 - py1) * 0.4

            # 头部不在画面内（人只有下半身可见），跳过判定
            if head_top < img_h * 0.02:
                head_not_visible.append(pi)
                continue

            best_hj = -1
            best_dist = float('inf')
            for hi, (hx1, hy1, hx2, hy2, hconf) in enumerate(helmet_boxes):
                if hi in matched_helmets:
                    continue
                hcx = (hx1 + hx2) / 2
                hcy = (hy1 + hy2) / 2
                if px1 <= hcx <= px2 and head_top <= hcy <= head_bottom:
                    dist = abs(hcx - (px1 + px2) / 2) + abs(hcy - (py1 + py2) / 2) * 0.3
                    if dist < best_dist:
                        best_dist = dist
                        best_hj = hi
            if best_hj >= 0:
                person_helmet_map[pi] = best_hj
                matched_helmets.add(best_hj)

        matched = []
        no_helmet = []
        for pi, pb in enumerate(person_boxes):
            if pi in head_not_visible:
                continue  # 头部不在画面内，不判定
            if pi in person_helmet_map:
                matched.append({"person": pb, "helmet": helmet_boxes[person_helmet_map[pi]]})
            else:
                no_helmet.append({"person": pb})

        return {
            "person_boxes": person_boxes,
            "helmet_boxes": helmet_boxes,
            "matched": matched,
            "no_helmet": no_helmet,
            "inference_ms": t1 + t2,
        }

    async def detect_all(
        self,
        frame: np.ndarray,
        confidence_threshold: Optional[float] = None,
        tracker: Optional[ByteTrack] = None,
    ) -> List[Tuple[str, sv.Detections, float]]:
        """Run detection with all models.

        Returns:
            List of (model_name, detections, inference_time) tuples
        """
        results = []

        for model_name in self._models.keys():
            try:
                detections, inference_time = await self.detect_with_model(
                    frame, model_name, confidence_threshold, tracker
                )
                results.append((model_name, detections, inference_time))
            except Exception as e:
                logger.error(f"detection_error_{model_name}", error=str(e))

        return results

    def get_class_name(self, model_name: str, class_id: int) -> str:
        """Map model class ID to business alarm type."""
        mapping = self._class_mapping.get(model_name, {})
        return mapping.get(str(class_id), f"unknown_{class_id}")

    def is_alarm_class(self, class_name: str) -> bool:
        """Check if a class should trigger an alarm."""
        return class_name in settings.ALARM_CLASSES


# Singleton instance
detector = MultiModelDetector()
