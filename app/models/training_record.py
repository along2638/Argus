from sqlalchemy import Column, BigInteger, String, Integer, Float, Text, DateTime, JSON, func
from app.db import Base


class TrainingRecord(Base):
    __tablename__ = "training_record"
    __table_args__ = {"comment": "模型训练记录表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    model_name = Column(String(64), nullable=False, comment="模型名称")
    dataset_name = Column(String(128), comment="训练数据集名称")
    epochs = Column(Integer, comment="训练轮数")
    batch_size = Column(Integer, comment="批大小")
    img_size = Column(Integer, comment="输入图片尺寸")
    best_map50 = Column(Float, comment="最佳mAP@0.5")
    best_map50_95 = Column(Float, comment="最佳mAP@0.5:0.95")
    model_path = Column(Text, comment="训练产物路径")
    config = Column(JSON, comment="训练配置参数")
    status = Column(String(16), default="pending", comment="状态: pending/running/completed/failed")
    started_at = Column(DateTime, comment="开始时间")
    finished_at = Column(DateTime, comment="完成时间")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
