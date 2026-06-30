"""测试安全帽模型检测结果"""
import onnxruntime as ort
import numpy as np
import cv2
import sys
import os

sys.path.insert(0, '.')
os.environ["ONNXRUNTIME_LOG_LEVEL"] = "3"

from app.config import settings

sess = ort.InferenceSession(settings.HELMET_MODEL_PATH, providers=["CPUExecutionProvider"])
input_name = sess.get_inputs()[0].name

test_img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
img = cv2.resize(test_img, (640, 640)).astype(np.float32) / 255.0
img = img.transpose(2, 0, 1)
blob = np.expand_dims(img, axis=0)

output = sess.run(None, {input_name: blob})[0]
print(f"输出 shape: {output.shape}")

raw = output[0]
if raw.ndim == 2 and raw.shape[1] > 6 and raw.shape[0] < raw.shape[1]:
    raw = raw.T

class_scores = raw[:, 4:7]
if class_scores.max() > 1.0:
    class_scores = 1.0 / (1.0 + np.exp(-class_scores))

scores = class_scores.max(axis=1)
class_ids = class_scores.argmax(axis=1)

class_names = {0: "helmet", 1: "no-helmet", 2: "person"}
for threshold in [0.01, 0.05, 0.1, 0.2, 0.3]:
    print(f"\n阈值 {threshold} 时:")
    for cls_id, cls_name in class_names.items():
        mask = (class_ids == cls_id) & (scores >= threshold)
        count = mask.sum()
        max_conf = scores[mask].max() if count > 0 else 0
        print(f"  {cls_name}: {count} 个, 最高置信度 {max_conf:.4f}")
