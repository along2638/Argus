from sqlalchemy import Column, BigInteger, String, Integer, Float, DateTime, func
from app.db import Base


class DetectionBox(Base):
    __tablename__ = "detection_box"
    __table_args__ = {"comment": "检测框表(像素坐标)"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    result_id = Column(BigInteger, nullable=False, index=True, comment="关联检测结果ID")
    class_id = Column(Integer, nullable=False, comment="类别ID")
    class_name = Column(String(64), nullable=False, comment="类别名称")
    confidence = Column(Float, nullable=False, comment="检测置信度")
    bbox_x1 = Column(Float, nullable=False, comment="框左上角X(像素)")
    bbox_y1 = Column(Float, nullable=False, comment="框左上角Y(像素)")
    bbox_x2 = Column(Float, nullable=False, comment="框右下角X(像素)")
    bbox_y2 = Column(Float, nullable=False, comment="框右下角Y(像素)")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
