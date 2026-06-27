#!/usr/bin/env python3
"""
YOLO 训练脚本 — 训练完成后自动写入训练记录

用法:
    python scripts/train.py --data fire_yolo/data.yaml --model yolov8s.pt --epochs 100 --name fire_smoke_v3

依赖:
    pip install ultralytics
"""

import argparse
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def train_and_record(args):
    from ultralytics import YOLO

    print(f"开始训练: {args.model}")
    print(f"  数据集: {args.data}")
    print(f"  轮数: {args.epochs}")
    print(f"  批大小: {args.batch}")
    print(f"  图片尺寸: {args.imgsz}")

    model = YOLO(args.model)

    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        name=args.name,
        exist_ok=True,
        patience=args.patience,
        save=True,
        plots=True,
        lr0=args.lr,
        lrf=0.01,
        momentum=0.937,
        weight_decay=0.0005,
    )

    # 提取指标
    metrics = results.results_dict
    best_map50 = metrics.get("metrics/mAP50(B)", 0)
    best_map50_95 = metrics.get("metrics/mAP50-95(B)", 0)
    model_path = str(results.save_dir / "weights" / "best.pt")

    print(f"\n训练完成!")
    print(f"  mAP@0.5: {best_map50:.4f}")
    print(f"  mAP@0.5:0.95: {best_map50_95:.4f}")
    print(f"  模型路径: {model_path}")

    # 自动写入训练记录
    if args.record:
        try:
            import urllib.request
            import json

            payload = json.dumps({
                "model_name": args.name,
                "dataset_name": args.data,
                "epochs": args.epochs,
                "batch_size": args.batch,
                "img_size": args.imgsz,
                "best_map50": best_map50,
                "best_map50_95": best_map50_95,
                "model_path": model_path,
                "status": "completed",
            }).encode()

            # 需要先登录获取 token
            login_data = json.dumps({"username": args.user, "password": args.password}).encode()
            req = urllib.request.Request(
                f"{args.api_url}/api/v1/auth/login",
                data=login_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                login_result = json.loads(resp.read())
                token = login_result["token"]

            req = urllib.request.Request(
                f"{args.api_url}/api/v1/auth/training",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
                if result.get("success"):
                    print("训练记录已自动写入系统")
                else:
                    print(f"写入失败: {result.get('detail', '未知错误')}")
        except Exception as e:
            print(f"写入训练记录失败: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YOLO 训练脚本（自动记录训练结果）")
    parser.add_argument("--data", required=True, help="数据集配置文件 (data.yaml)")
    parser.add_argument("--model", default="yolov8s.pt", help="预训练模型")
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数")
    parser.add_argument("--batch", type=int, default=16, help="批大小")
    parser.add_argument("--imgsz", type=int, default=640, help="输入图片尺寸")
    parser.add_argument("--patience", type=int, default=30, help="早停轮数")
    parser.add_argument("--lr", type=float, default=0.01, help="初始学习率")
    parser.add_argument("--name", default="train", help="实验名称")
    parser.add_argument("--record", action="store_true", default=True, help="训练后自动写入记录")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Argus API 地址")
    parser.add_argument("--user", default="admin", help="API 登录用户名")
    parser.add_argument("--password", default="admin123", help="API 登录密码")
    args = parser.parse_args()

    train_and_record(args)
