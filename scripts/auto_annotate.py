#!/usr/bin/env python3
"""
自动标注工具 - 用 YOLO 模型预标注图片，生成 YOLO 格式标签

用法:
    # 使用 .pt 模型（推荐，精度更高）
    python scripts/auto_annotate.py --model models/pt/yolo11l.pt --images fire_smoke_data/to_annotate

    # 使用 .onnx 模型
    python scripts/auto_annotate.py --model models/onnx/fire_smoke_v2.onnx --images fire_smoke_data/to_annotate

    # 指定置信度阈值
    python scripts/auto_annotate.py --model models/pt/yolo11l.pt --images fire_smoke_data/to_annotate --conf 0.25

    # 生成预览图（可视化标注结果）
    python scripts/auto_annotate.py --model models/pt/yolo11l.pt --images fire_smoke_data/to_annotate --preview

    # 仅处理未标注的图片
    python scripts/auto_annotate.py --model models/pt/yolo11l.pt --images fire_smoke_data/to_annotate --skip-annotated
"""

import argparse
import os
import shutil
from pathlib import Path

import cv2
import numpy as np


def load_model(model_path: str):
    """加载 YOLO 模型（支持 .pt 和 .onnx）"""
    from ultralytics import YOLO
    print(f"加载模型: {model_path}")
    model = YOLO(model_path)
    print(f"模型类别: {model.names}")
    return model


def get_image_files(image_dir: str) -> list:
    """获取目录下所有图片文件"""
    extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    files = []
    for f in sorted(os.listdir(image_dir)):
        if Path(f).suffix.lower() in extensions:
            files.append(os.path.join(image_dir, f))
    return files


def check_has_label(label_dir: str, image_name: str) -> bool:
    """检查图片是否已有标注"""
    label_name = Path(image_name).stem + '.txt'
    label_path = os.path.join(label_dir, label_name)
    return os.path.exists(label_path) and os.path.getsize(label_path) > 0


def annotate_single(model, image_path: str, conf: float = 0.3) -> list:
    """对单张图片进行标注，返回 YOLO 格式标签列表"""
    results = model(image_path, conf=conf, verbose=False)
    
    # 读取图片获取尺寸
    img = cv2.imread(image_path)
    if img is None:
        print(f"  警告: 无法读取图片 {image_path}")
        return []
    h, w = img.shape[:2]
    
    labels = []
    for r in results:
        if r.boxes is None or len(r.boxes) == 0:
            continue
        for box in r.boxes:
            cls = int(box.cls[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf_score = float(box.conf[0])
            
            # 转换为 YOLO 格式 (center_x, center_y, width, height) 归一化
            cx = (x1 + x2) / 2 / w
            cy = (y1 + y2) / 2 / h
            bw = (x2 - x1) / w
            bh = (y2 - y1) / h
            
            # 边界检查
            cx = max(0, min(1, cx))
            cy = max(0, min(1, cy))
            bw = max(0, min(1, bw))
            bh = max(0, min(1, bh))
            
            # 跳过过小的框
            if bw < 0.01 or bh < 0.01:
                continue
            
            labels.append(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    
    return labels


def generate_preview(image_path: str, labels: list, model_names: dict, output_path: str):
    """生成标注预览图"""
    img = cv2.imread(image_path)
    if img is None:
        return
    
    h, w = img.shape[:2]
    colors = [
        (0, 255, 0),    # 绿色
        (255, 0, 0),    # 蓝色
        (0, 0, 255),    # 红色
        (255, 255, 0),  # 青色
        (0, 255, 255),  # 黄色
        (255, 0, 255),  # 紫色
    ]
    
    for label in labels:
        parts = label.strip().split()
        if len(parts) != 5:
            continue
        
        cls = int(parts[0])
        cx, cy, bw, bh = map(float, parts[1:5])
        
        # 转换回像素坐标
        x1 = int((cx - bw / 2) * w)
        y1 = int((cy - bh / 2) * h)
        x2 = int((cx + bw / 2) * w)
        y2 = int((cy + bh / 2) * h)
        
        color = colors[cls % len(colors)]
        class_name = model_names.get(str(cls), f"cls_{cls}")
        
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, class_name, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    
    cv2.imwrite(output_path, img)


def main():
    parser = argparse.ArgumentParser(description="YOLO 自动标注工具")
    parser.add_argument("--model", required=True, help="模型路径 (.pt 或 .onnx)")
    parser.add_argument("--images", required=True, help="图片目录")
    parser.add_argument("--output", default=None, help="标签输出目录 (默认: <images>_labels)")
    parser.add_argument("--conf", type=float, default=0.3, help="置信度阈值 (默认: 0.3)")
    parser.add_argument("--preview", action="store_true", help="生成预览图")
    parser.add_argument("--preview-dir", default=None, help="预览图输出目录")
    parser.add_argument("--skip-annotated", action="store_true", help="跳过已有标注的图片")
    parser.add_argument("--copy-images", action="store_true", help="复制图片到输出目录（用于创建新数据集）")
    args = parser.parse_args()
    
    # 检查路径
    if not os.path.exists(args.model):
        print(f"错误: 模型文件不存在 {args.model}")
        return
    if not os.path.exists(args.images):
        print(f"错误: 图片目录不存在 {args.images}")
        return
    
    # 设置输出目录
    if args.output:
        label_dir = args.output
    else:
        label_dir = args.images.rstrip('/\\') + '_labels'
    os.makedirs(label_dir, exist_ok=True)
    
    # 预览图目录
    preview_dir = args.preview_dir or (args.images.rstrip('/\\') + '_preview')
    if args.preview:
        os.makedirs(preview_dir, exist_ok=True)
    
    # 图片输出目录（如果需要复制）
    if args.copy_images:
        image_out_dir = os.path.join(os.path.dirname(label_dir), 'images')
        os.makedirs(image_out_dir, exist_ok=True)
    
    # 加载模型
    model = load_model(args.model)
    model_names = model.names
    
    # 获取图片列表
    image_files = get_image_files(args.images)
    print(f"找到 {len(image_files)} 张图片")
    
    # 统计
    total = len(image_files)
    annotated = 0
    skipped = 0
    empty = 0
    
    for i, img_path in enumerate(image_files, 1):
        img_name = os.path.basename(img_path)
        print(f"[{i}/{total}] {img_name}", end=" ")
        
        # 检查是否已有标注
        if args.skip_annotated and check_has_label(label_dir, img_name):
            print("(已有标注，跳过)")
            skipped += 1
            continue
        
        # 自动标注
        labels = annotate_single(model, img_path, args.conf)
        
        if not labels:
            print("(未检测到目标)")
            empty += 1
            continue
        
        # 保存标签
        label_name = Path(img_name).stem + '.txt'
        label_path = os.path.join(label_dir, label_name)
        with open(label_path, 'w') as f:
            f.write('\n'.join(labels))
        
        detected_classes = [model_names.get(l.split()[0], l.split()[0]) for l in labels]
        print(f"检测到 {len(labels)} 个目标: {', '.join(detected_classes)}")
        annotated += 1
        
        # 生成预览图
        if args.preview:
            preview_path = os.path.join(preview_dir, img_name)
            generate_preview(img_path, labels, model_names, preview_path)
        
        # 复制图片
        if args.copy_images:
            dst = os.path.join(image_out_dir, img_name)
            if not os.path.exists(dst):
                shutil.copy2(img_path, dst)
    
    # 打印统计
    print("\n" + "=" * 50)
    print("标注完成!")
    print(f"  总计: {total} 张图片")
    print(f"  已标注: {annotated} 张")
    print(f"  跳过: {skipped} 张")
    print(f"  未检测到: {empty} 张")
    print(f"  标签输出: {label_dir}")
    if args.preview:
        print(f"  预览图: {preview_dir}")
    print("=" * 50)


if __name__ == '__main__':
    main()
