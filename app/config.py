from pydantic_settings import BaseSettings
from pydantic import Field
from pydantic import ConfigDict
from typing import Dict, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # MinIO Configuration
    MINIO_ENDPOINT: str = "192.168.6.227:9000"
    MINIO_BUCKET: str = "yolo"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "Mxminio@2024"
    MINIO_SECURE: bool = False

    # PostgreSQL Configuration
    PG_DSN: str = "postgresql://system:mx%401232025@192.168.2.65:54321/yolo_alarm"

    # Redis Configuration
    REDIS_URL: str = "redis://:Redis%40dev2025@192.168.2.100:16377/0"

    # Model Configuration（ONNX 格式）
    # 通用模型（人）
    YOLO_ONNX_PATH: str = "./models/onnx/yolo11l.onnx"
    # 火灾/烟雾检测模型
    FIRE_SMOKE_MODEL_PATH: str = "./models/onnx/fire_smoke_v2.onnx"
    # 安全帽检测模型
    HELMET_MODEL_PATH: str = "./models/onnx/helmet_fp16.onnx"

    # Application Configuration
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    MAX_CONCURRENT_STREAMS: int = 10
    CONFIDENCE_THRESHOLD: float = 0.3  # 通用检测阈值
    FIRE_SMOKE_CONFIDENCE_THRESHOLD: float = 0.01  # 火灾烟雾检测需要较低阈值

    # Alarm Configuration
    ALARM_COOLDOWN_TTL: int = 30  # seconds

    # ARQ Worker Configuration
    ARQ_MAX_JOBS: int = 20
    ARQ_QUEUE_WARNING_THRESHOLD: int = 100

    # Class Mapping: model class ID -> business alarm type
    # 通用模型类别（COCO 数据集）
    CLASS_MAPPING: Dict[str, str] = Field(default={
        # 人
        "0": "person",
        # 动物
        "14": "bird",       # 鸟
        "15": "cat",        # 猫
        "16": "dog",        # 狗
        "17": "horse",      # 马
        "18": "sheep",      # 羊
        "19": "cow",        # 牛
        "20": "elephant",   # 大象
        "21": "bear",       # 熊
        "22": "zebra",      # 斑马
        "23": "giraffe",    # 长颈鹿
    })

    # 火灾/烟雾模型类别
    FIRE_SMOKE_CLASS_MAPPING: Dict[str, str] = Field(default={
        "0": "fire",       # 火灾
    })

    # 安全帽模型类别
    HELMET_CLASS_MAPPING: Dict[str, str] = Field(default={
        "0": "helmet",      # 佩戴安全帽
        "1": "no-helmet",   # 未佩戴安全帽（头部）
        "2": "person",      # 人
    })

    # Only trigger alarm for these classes
    ALARM_CLASSES: List[str] = Field(default=[
        # 人/动物（通用模型，归入异物入侵）
        "person", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe",
        # 火灾/烟雾（使用专门模型）
        "fire", "smoke",
        # 未佩戴安全帽（使用专门模型）
        "no-helmet",
    ])



# Singleton instance
settings = Settings()
