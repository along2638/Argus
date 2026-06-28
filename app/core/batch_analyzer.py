"""Batch video analysis — process multiple video files and generate HTML report."""

import asyncio
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from app.core.detector import detector
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def analyze_video_file(
    video_path: str,
    model_name: str = "general",
    confidence: float = 0.3,
    frame_interval: int = 10,
) -> dict:
    """Analyze a single video file and return results."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"error": f"Cannot open video: {video_path}"}

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
                frame, model_name, confidence_threshold=confidence
            )
            if len(detections) > 0:
                frame_results = []
                for i in range(len(detections)):
                    class_id = int(detections.class_id[i])
                    conf = float(detections.confidence[i])
                    bbox = detections.xyxy[i].tolist()
                    class_name = detector.get_class_name(model_name, class_id)
                    frame_results.append({
                        "class_name": class_name,
                        "confidence": round(conf, 4),
                        "bbox": [round(x, 1) for x in bbox],
                    })
                results.append({
                    "frame": frame_idx,
                    "time": round(frame_idx / fps, 2),
                    "detections": frame_results,
                })
        frame_idx += 1

    cap.release()

    return {
        "file": os.path.basename(video_path),
        "total_frames": total_frames,
        "analyzed_frames": frame_idx,
        "frame_interval": frame_interval,
        "fps": round(fps, 1),
        "frames_with_detections": len(results),
        "results": results,
    }


async def batch_analyze(
    directory: str,
    model_name: str = "general",
    confidence: float = 0.3,
    frame_interval: int = 10,
) -> dict:
    """Analyze all video files in a directory.

    Returns a summary dict with per-file results.
    """
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".rtsp"}
    try:
        files = [
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if Path(f).suffix.lower() in video_exts
        ]
    except FileNotFoundError:
        return {"error": f"Directory not found: {directory}", "files": []}

    if not files:
        return {"error": "No video files found", "files": []}

    file_results = []
    for vf in sorted(files):
        logger.info("batch_analyzing_file", file=vf)
        result = await analyze_video_file(vf, model_name, confidence, frame_interval)
        file_results.append(result)

    total_detections = sum(r.get("frames_with_detections", 0) for r in file_results)
    all_classes = set()
    for r in file_results:
        for frame_r in r.get("results", []):
            for det in frame_r.get("detections", []):
                all_classes.add(det["class_name"])

    return {
        "directory": directory,
        "model": model_name,
        "confidence": confidence,
        "total_files": len(files),
        "total_detections_frames": total_detections,
        "classes_found": sorted(all_classes),
        "files": file_results,
    }


def generate_html_report(analysis: dict) -> str:
    """Generate an HTML report from batch analysis results."""
    files = analysis.get("files", [])
    classes_found = analysis.get("classes_found", [])

    rows = ""
    for f in files:
        fname = f.get("file", "unknown")
        total = f.get("total_frames", 0)
        det_frames = f.get("frames_with_detections", 0)
        fps = f.get("fps", 0)
        det_rate = f"{det_frames/total*100:.1f}%" if total > 0 else "0%"

        class_summary = {}
        for frame_r in f.get("results", []):
            for det in frame_r.get("detections", []):
                cn = det["class_name"]
                class_summary[cn] = class_summary.get(cn, 0) + 1

        classes_str = ", ".join(f"{k}({v})" for k, v in sorted(class_summary.items()))

        rows += f"""
        <tr>
            <td>{fname}</td>
            <td>{total}</td>
            <td>{det_frames}</td>
            <td>{det_rate}</td>
            <td>{fps}</td>
            <td>{classes_str}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Argus 批量分析报告</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        h1 {{ color: #1a1a1a; }}
        .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .stat-value {{ font-size: 2rem; font-weight: 700; }}
        .stat-label {{ color: #666; font-size: 0.9rem; }}
        table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #fafafa; font-weight: 600; }}
        tr:hover {{ background: #f9f9f9; }}
        .footer {{ margin-top: 30px; color: #999; font-size: 0.85rem; }}
    </style>
</head>
<body>
    <h1>Argus 批量视频分析报告</h1>
    <p>模型: {analysis.get('model', 'N/A')} | 置信度阈值: {analysis.get('confidence', 0)} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

    <div class="summary">
        <div class="stat"><div class="stat-value">{analysis.get('total_files', 0)}</div><div class="stat-label">分析文件数</div></div>
        <div class="stat"><div class="stat-value">{analysis.get('total_detections_frames', 0)}</div><div class="stat-label">检出帧数</div></div>
        <div class="stat"><div class="stat-value">{len(classes_found)}</div><div class="stat-label">检出类别数</div></div>
        <div class="stat"><div class="stat-value">{', '.join(classes_found) or '无'}</div><div class="stat-label">检出类别</div></div>
    </div>

    <table>
        <thead>
            <tr><th>文件名</th><th>总帧数</th><th>检出帧</th><th>检出率</th><th>FPS</th><th>检出类别</th></tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>

    <div class="footer">Generated by Argus Smart Monitoring System</div>
</body>
</html>"""

    return html
