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

    async def _detect():
        # 使用轻量模型：Nano 检测人 + FP16 检测帽子
        return await asyncio.gather(
            detector.detect_person_lightweight(frame, confidence_threshold=0.3),
            detector.detect_helmet_lightweight(frame, confidence_threshold=0.01),
        )

    start = time.time()
    results = asyncio.run(_detect())
    total_ms = (time.time() - start) * 1000
    (person_dets, t1), (helmet_dets, t2) = results

    img_h, img_w = frame.shape[:2]
    helmet_thresh = settings.HELMET_CONFIRM_THRESHOLD

    if debug:
        print(f"  [DEBUG] 图片尺寸: {img_w}x{img_h}")
        print(f"  [DEBUG] 推理耗时: 人={t1:.1f}ms 帽子={t2:.1f}ms 总计={total_ms:.1f}ms")
        print(f"  [DEBUG] 通用模型原始检测: {len(person_dets)} 个")
        for i in range(len(person_dets)):
            cid = int(person_dets.class_id[i])
            cname = detector.get_class_name("general", cid)
            conf = float(person_dets.confidence[i])
            bbox = person_dets.xyxy[i].tolist()
            area_ratio = (bbox[2]-bbox[0]) * (bbox[3]-bbox[1]) / (img_w * img_h)
            print(f"    {cname} conf={conf:.3f} bbox={[int(x) for x in bbox]} area={area_ratio:.4f}")
        print(f"  [DEBUG] 安全帽模型原始检测: {len(helmet_dets)} 个")
        for i in range(len(helmet_dets)):
            cid = int(helmet_dets.class_id[i])
            cname = detector.get_class_name("helmet", cid)
            conf = float(helmet_dets.confidence[i])
            bbox = helmet_dets.xyxy[i].tolist()
            print(f"    {cname} conf={conf:.3f} bbox={[int(x) for x in bbox]}")

    # 提取 person 框
    person_boxes = []
    for i in range(len(person_dets)):
        cid = int(person_dets.class_id[i])
        cname = detector.get_class_name("general", cid)
        if cname != "person":
            continue
        conf = float(person_dets.confidence[i])
        bbox = person_dets.xyxy[i].tolist()
        x1, y1, x2, y2 = bbox
        if (x2 - x1) * (y2 - y1) / (img_w * img_h) < 0.02:
            continue
        person_boxes.append({"conf": conf, "bbox": bbox})

    # 提取 helmet 框
    helmet_boxes = []
    for i in range(len(helmet_dets)):
        cid = int(helmet_dets.class_id[i])
        cname = detector.get_class_name("helmet", cid)
        if cname != "helmet":
            continue
        conf = float(helmet_dets.confidence[i])
        if conf < helmet_thresh:
            continue
        bbox = helmet_dets.xyxy[i].tolist()
        helmet_boxes.append({"conf": conf, "bbox": bbox})

    if debug:
        print(f"  [DEBUG] 过滤后: person={len(person_boxes)}, helmet={len(helmet_boxes)}")
        for pb in person_boxes:
            print(f"    person: bbox={[int(x) for x in pb['bbox']]}")
        for hb in helmet_boxes:
            print(f"    helmet: bbox={[int(x) for x in hb['bbox']]} conf={hb['conf']:.3f}")

    # 一对一贪心匹配
    matched_helmets = set()
    person_helmet_map = {}
    for pi, pb in enumerate(person_boxes):
        px1, py1, px2, py2 = pb["bbox"]
        head_top = py1
        head_bottom = py1 + (py2 - py1) * 0.4
        best_hj = -1
        best_dist = float('inf')
        for hi, hb in enumerate(helmet_boxes):
            if hi in matched_helmets:
                continue
            hx1, hy1, hx2, hy2 = hb["bbox"]
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

    # 统计结果
    helmet_count = len(person_helmet_map)
    no_helmet_count = len(person_boxes) - helmet_count

    return len(person_boxes), helmet_count, no_helmet_count


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
