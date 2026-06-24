#!/usr/bin/env python3
"""
YOLOv11n ONNX FP16 Export Script

This script exports a trained YOLOv11n model to ONNX format with FP16 quantization.

Usage:
    python scripts/export_onnx.py --model path/to/yolov11n.pt --output models/yolov11n_fp16.onnx

Requirements:
    pip install ultralytics onnxruntime-gpu
"""

import argparse
import sys
from pathlib import Path


def export_to_onnx(model_path: str, output_path: str, img_size: int = 640) -> None:
    """Export YOLO model to ONNX FP16 format.

    Args:
        model_path: Path to the PyTorch model (.pt file)
        output_path: Path for the output ONNX model
        img_size: Input image size (default: 640)
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Error: ultralytics not installed. Run: pip install ultralytics")
        sys.exit(1)

    print(f"Loading model from: {model_path}")
    model = YOLO(model_path)

    print(f"Exporting to ONNX with FP16 quantization...")
    print(f"  Image size: {img_size}x{img_size}")
    print(f"  Output path: {output_path}")

    # Export to ONNX with FP16
    success = model.export(
        format="onnx",
        imgsz=img_size,
        half=True,  # FP16 quantization
        simplify=True,  # Simplify model
        opset=12,  # ONNX opset version
    )

    if success:
        # The ultralytics library saves the file with .onnx extension
        # Move/rename to desired output path
        exported_path = Path(model_path).with_suffix(".onnx")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if exported_path != output:
            import shutil
            shutil.move(str(exported_path), str(output))

        print(f"\n✓ Model exported successfully!")
        print(f"  Output: {output}")
        print(f"  Size: {output.stat().st_size / 1024 / 1024:.2f} MB")
    else:
        print("✗ Export failed!")
        sys.exit(1)


def verify_onnx_model(model_path: str) -> None:
    """Verify the exported ONNX model.

    Args:
        model_path: Path to the ONNX model
    """
    try:
        import onnxruntime as ort
        import numpy as np
    except ImportError:
        print("Warning: onnxruntime not installed, skipping verification")
        return

    print(f"\nVerifying ONNX model: {model_path}")

    # Create inference session
    providers = ["CPUExecutionProvider"]
    if "CUDAExecutionProvider" in ort.get_available_providers():
        providers.insert(0, "CUDAExecutionProvider")

    session = ort.InferenceSession(model_path, providers=providers)

    # Get model info
    input_meta = session.get_inputs()[0]
    output_meta = session.get_outputs()[0]

    print(f"  Input:  {input_meta.name} - Shape: {input_meta.shape} - Type: {input_meta.type}")
    print(f"  Output: {output_meta.name} - Shape: {output_meta.shape} - Type: {output_meta.type}")
    print(f"  Provider: {session.get_providers()[0]}")

    # Test inference with dummy data
    input_shape = input_meta.shape
    if isinstance(input_shape[0], str):
        input_shape[0] = 1  # Batch size

    dummy_input = np.random.randn(*input_shape).astype(np.float16 if "float16" in input_meta.type else np.float32)

    try:
        outputs = session.run(None, {input_meta.name: dummy_input})
        print(f"  Inference test: ✓ Success")
        print(f"  Output shape: {outputs[0].shape}")
    except Exception as e:
        print(f"  Inference test: ✗ Failed - {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Export YOLOv11n model to ONNX FP16 format"
    )
    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Path to the PyTorch model (.pt file)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="models/yolov11n_fp16.onnx",
        help="Output path for ONNX model (default: models/yolov11n_fp16.onnx)",
    )
    parser.add_argument(
        "--img-size",
        type=int,
        default=640,
        help="Input image size (default: 640)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify the exported model",
    )

    args = parser.parse_args()

    # Check if model exists
    if not Path(args.model).exists():
        print(f"Error: Model file not found: {args.model}")
        sys.exit(1)

    # Export model
    export_to_onnx(args.model, args.output, args.img_size)

    # Verify if requested
    if args.verify:
        verify_onnx_model(args.output)


if __name__ == "__main__":
    main()
