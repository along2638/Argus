#!/usr/bin/env python3
"""
批量自动标注 - 支持多目录、多模型、生成数据集配置

用法:
    # 标注多个目录
    python scripts/batch_annotate.py --model models/pt/yolo11l.pt --dirs fire_smoke_data/dark_fire_video fire_smoke_data/light_fire_video

    # 生成完整数据集（图片+标签+data.yaml）
    python scripts/batch_annotate.py --model models/pt/yolo11l.pt --dirs fire_smoke_data/to_annotate --create-dataset --dataset-name fire_smoke_v2

    # 高置信度筛选（只保留高置信度标注）
    python scripts/batch_annotate.py --model models/pt/yolo11l.pt --dirs fire_smoke_data/to_annotate --conf 0.5
"""

import argparse
import os
import random
import shutil
from pathlib import Path

import yaml


def get_image_files(directory: str) -> list:
    """获取目录下所有图片文件"""
    extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    files = []
    for f in sorted(os.listdir(directory)):
        if Path(f).suffix.lower() in extensions:
            files.append(os.path.join(directory, f))
    return files


def auto_annotate(model, image_path: str, conf: float) -> list:
    """自动标注单张图片"""
    import cv2
    
    results = model(image_path, conf=conf, verbose=False)
    
    img = cv2.imread(image_path)
    if img is None:
        return []
    h, w = img.shape[:2]
    
    labels = []
    for r in results:
        if r.boxes is None or len(r.boxes) == 0:
            continue
        for box in r.boxes:
            cls = int(box.cls[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            
            cx = (x1 + x2) / 2 / w
            cy = (y1 + y2) / 2 / h
            bw = (x2 - x1) / w
            bh = (y2 - y1) / h
            
            cx = max(0, min(1, cx))
            cy = max(0, min(1, cy))
            bw = max(0, min(1, bw))
            bh = max(0, min(1, bh))
            
            if bw < 0.01 or bh < 0.01:
                continue
            
            labels.append(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    
    return labels


def split_dataset(images: list, labels: dict, train_ratio: float = 0.8, val_ratio: float = 0.15, test_ratio: float = 0.05):
    """拆分数据集为 train/val/test"""
    random.shuffle(images)
    total = len(images)
    train_end = int(total * train_ratio)
    val_end = int(total * (train_ratio + val_ratio))
    
    splits = {
        'train': images[:train_end],
        'val': images[train_end:val_end],
        'test': images[val_end:],
    }
    
    return splits


def create_dataset_structure(dataset_dir: str, splits: dict, all_labels: dict):
    """创建 YOLO 数据集目录结构"""
    for split_name, split_images in splits.items():
        img_dir = os.path.join(dataset_dir, split_name, 'images')
        lbl_dir = os.path.join(dataset_dir, split_name, 'labels')
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(lbl_dir, exist_ok=True)
        
        for img_path in split_images:
            img_name = os.path.basename(img_path)
            lbl_name = Path(img_name).stem + '.txt'
            
            # 复制图片
            shutil.copy2(img_path, os.path.join(img_dir, img_name))
            
            # 复制标签
            if img_path in all_labels:
                lbl_content = '\n'.join(all_labels[img_path])
                with open(os.path.join(lbl_dir, lbl_name), 'w') as f:
                    f.write(lbl_content)


def create_data_yaml(dataset_dir: str, dataset_name: str, class_names: dict):
    """生成 data.yaml 配置文件"""
    data = {
        'path': os.path.abspath(dataset_dir),
        'train': 'train/images',
        'val': 'val/images',
        'test': 'test/images',
        'nc': len(class_names),
        'names': class_names,
    }
    
    yaml_path = os.path.join(dataset_dir, 'data.yaml')
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    
    return yaml_path


def main():
    parser = argparse.ArgumentParser(description="批量自动标注工具")
    parser.add_argument("--model", required=True, help="模型路径 (.pt)")
    parser.add_argument("--dirs", nargs="+", required=True, help="图片目录列表")
    parser.add_argument("--conf", type=float, default=0.3, help="置信度阈值")
    parser.add_argument("--output", default="auto_annotated", help="输出根目录")
    parser.add_argument("--create-dataset", action="store_true", help="创建完整数据集结构")
    parser.add_argument("--dataset-name", default="dataset", help="数据集名称")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="训练集比例")
    parser.add_argument("--val-ratio", type=float, default=0.15, help="验证集比例")
    parser.add_argument("--test-ratio", type=float, default=0.05, help="测试集比例")
    args = parser.parse_args()
    
    # 加载模型
    from ultralytics import YOLO
    print(f"加载模型: {args.model}")
    model = YOLO(args.model)
    class_names = model.names
    print(f"模型类别: {class_names}")
    
    # 收集所有图片
    all_images = []
    for d in args.dirs:
        if not os.path.exists(d):
            print(f"警告: 目录不存在 {d}")
            continue
        imgs = get_image_files(d)
        print(f"  {d}: {len(imgs)} 张图片")
        all_images.extend(imgs)
    
    if not all_images:
        print("错误: 未找到任何图片")
        return
    
    print(f"\n总计 {len(all_images)} 张图片，开始标注...")
    
    # 标注所有图片
    all_labels = {}
    stats = {'total': len(all_images), 'annotated': 0, 'empty': 0}
    
    for i, img_path in enumerate(all_images, 1):
        print(f"[{i}/{stats['total']}] {os.path.basename(img_path)}", end=" ")
        
        labels = auto_annotate(model, img_path, args.conf)
        
        if not labels:
            print("(未检测到)")
            stats['empty'] += 1
            continue
        
        all_labels[img_path] = labels
        stats['annotated'] += 1
        print(f"✓ {len(labels)} 个目标")
    
    print(f"\n标注完成: {stats['annotated']}/{stats['total']} 张图片有标注")
    
    if args.create_dataset:
        # 创建数据集
        dataset_dir = os.path.join(args.output, args.dataset_name)
        os.makedirs(dataset_dir, exist_ok=True)
        
        # 拆分数据集
        splits = split_dataset(list(all_labels.keys()), all_labels, 
                              args.train_ratio, args.val_ratio, args.test_ratio)
        
        print(f"\n创建数据集: {dataset_dir}")
        print(f"  训练集: {len(splits['train'])} 张")
        print(f"  验证集: {len(splits['val'])} 张")
        print(f"  测试集: {len(splits['test'])} 张")
        
        # 创建目录结构
        create_dataset_structure(dataset_dir, splits, all_labels)
        
        # 生成 data.yaml
        yaml_path = create_data_yaml(dataset_dir, args.dataset_name, class_names)
        print(f"  配置文件: {yaml_path}")
        
        print(f"\n数据集创建完成! 可直接用于训练:")
        print(f"  yolo train data={yaml_path} model=yolov8s.pt epochs=100")
    else:
        # 简单输出模式
        label_dir = os.path.join(args.output, 'labels')
        os.makedirs(label_dir, exist_ok=True)
        
        for img_path, labels in all_labels.items():
            lbl_name = Path(os.path.basename(img_path)).stem + '.txt'
            with open(os.path.join(label_dir, lbl_name), 'w') as f:
                f.write('\n'.join(labels))
        
        print(f"\n标签输出: {label_dir}")


if __name__ == '__main__':
    main()
