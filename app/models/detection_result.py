from sqlalchemy import Column, BigInteger, String, Text, Float, Integer, DateTime, func
from app.db import Base


class DetectionResult(Base):
    __tablename__ = "detection_result"
    __table_args__ = {"comment": "图片检测结果表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    filename = Column(String(255), nullable=False, comment="原始文件名")
    image_path = Column(Text, comment="MinIO存储路径")
    model_name = Column(String(32), nullable=False, comment="模型名称: general/helmet/fire_smoke")
    confidence_threshold = Column(Float, nullable=False, comment="置信度阈值")
    inference_time_ms = Column(Float, comment="推理耗时(毫秒)")
    image_width = Column(Integer, comment="图片宽度(像素)")
    image_height = Column(Integer, comment="图片高度(像素)")
    detections_count = Column(Integer, default=0, comment="检测目标数")
    user_id = Column(BigInteger, comment="操作用户ID")
    detected_at = Column(DateTime, nullable=False, server_default=func.now(), comment="检测时间")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
