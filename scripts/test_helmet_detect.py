#!/usr/bin/env python3
"""测试安全帽检测：通用模型检测人 + 安全帽模型检测帽子，差集 = 没戴帽"""
import sys, os
sys.path.insert(0, '.')
os.environ["ONNXRUNTIME_LOG_LEVEL"] = "3"

import cv2
import numpy as np
import time
from app.config import settings
from app.core.detector import detector

# 预期结果
EXPECTED = {
    "1.png": {"person": 8, "helmet": 3, "no_helmet": 5},
    "2.png": {"person": 1, "helmet": 1, "no_helmet": 0},
    "3.png": {"person": 5, "helmet": 5, "no_helmet": 0},
    "4.png": {"person": 3, "helmet": 1, "no_helmet": 2},
    "5.png": {"person": 3, "helmet": 1, "no_helmet": 2},
    "6.png": {"person": 3, "helmet": 2, "no_helmet": 1},
}

def detect_helmet(image_path, debug=False):
    """运行安全帽检测，返回 (person_count, helmet_count, no_helmet_count)"""
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"  无法读取: {image_path}")
        return None

    import asyncio

    start = time.time()
    result = asyncio.run(detector.detect_helmet_combined(frame))
    total_ms = (time.time() - start) * 1000

    if debug:
        print(f"  [DEBUG] 图片尺寸: {frame.shape[1]}x{frame.shape[0]}")
        print(f"  [DEBUG] 推理耗时: {result['inference_ms']:.1f}ms (含后处理总计 {total_ms:.1f}ms)")
        print(f"  [DEBUG] 人检测: {len(result['person_boxes'])} 个")
        for pb in result["person_boxes"]:
            print(f"    person conf={pb[4]:.3f} bbox={list(pb[:4])}")
        print(f"  [DEBUG] 帽子检测: {len(result['helmet_boxes'])} 个")
        for hb in result["helmet_boxes"]:
            print(f"    helmet conf={hb[4]:.3f} bbox={list(hb[:4])}")
        print(f"  [DEBUG] 匹配结果: helmet={len(result['matched'])}, no-helmet={len(result['no_helmet'])}")

    helmet_count = len(result["matched"])
    no_helmet_count = len(result["no_helmet"])
    return len(result["person_boxes"]), helmet_count, no_helmet_count


def main():
    images_dir = "images"
    all_pass = True

    print("=" * 60)
    print("安全帽检测测试")
    print("=" * 60)
    print(f"{'图片':<10} {'期望人数':>8} {'检测人数':>8} {'期望戴帽':>8} {'检测戴帽':>8} {'期望未戴':>8} {'检测未戴':>8} {'结果':>6}")
    print("-" * 60)

    for img_name, expected in EXPECTED.items():
        img_path = os.path.join(images_dir, img_name)
        if not os.path.exists(img_path):
            # 尝试 jpg
            img_path = os.path.join(images_dir, img_name.replace(".png", ".jpg"))
        if not os.path.exists(img_path):
            print(f"{img_name:<10} 文件不存在，跳过")
            continue

        result = detect_helmet(img_path, debug=True)
        if result is None:
            all_pass = False
            continue

        person_count, helmet_count, no_helmet_count = result
        ep = expected["person"]
        eh = expected["helmet"]
        en = expected["no_helmet"]

        ok = (person_count == ep and helmet_count == eh and no_helmet_count == en)
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False

        print(f"{img_name:<10} {ep:>8} {person_count:>8} {eh:>8} {helmet_count:>8} {en:>8} {no_helmet_count:>8} {status:>6}")

    print("=" * 60)
    if all_pass:
        print("全部通过!")
    else:
        print("有失败项，需要继续优化")
    print("=" * 60)


if __name__ == "__main__":
    main()
