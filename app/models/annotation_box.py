from sqlalchemy import Column, BigInteger, String, Integer, Float, DateTime, func
from app.db import Base


class AnnotationBox(Base):
    __tablename__ = "annotation_box"
    __table_args__ = {"comment": "标注框表(YOLO格式)"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    image_id = Column(BigInteger, nullable=False, index=True, comment="关联图片ID")
    class_id = Column(Integer, nullable=False, comment="类别ID")
    class_name = Column(String(64), nullable=False, comment="类别名称: fire/smoke/person")
    cx = Column(Float, nullable=False, comment="中心点X(归一化0-1)")
    cy = Column(Float, nullable=False, comment="中心点Y(归一化0-1)")
    bw = Column(Float, nullable=False, comment="宽度(归一化0-1)")
    bh = Column(Float, nullable=False, comment="高度(归一化0-1)")
    confidence = Column(Float, comment="置信度(自动标注时有值)")
    annotator = Column(String(64), comment="标注人")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
