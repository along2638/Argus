from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, JSON, func
from app.db import Base


class Dataset(Base):
    __tablename__ = "dataset"
    __table_args__ = {"comment": "数据集配置表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    name = Column(String(128), nullable=False, unique=True, comment="数据集名称")
    description = Column(Text, comment="描述")
    class_mapping = Column(JSON, nullable=False, comment="类别映射 {id: name}")
    total_images = Column(Integer, default=0, comment="总图片数")
    train_count = Column(Integer, default=0, comment="训练集数量")
    val_count = Column(Integer, default=0, comment="验证集数量")
    test_count = Column(Integer, default=0, comment="测试集数量")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
