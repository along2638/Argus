"""Annotation snapshot model — version history for annotations."""

from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, func
from app.db import Base


class AnnotationSnapshot(Base):
    __tablename__ = "annotation_snapshot"
    __table_args__ = {"comment": "标注快照表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    image_id = Column(BigInteger, nullable=False, index=True, comment="关联标注图片ID")
    filename = Column(String(255), nullable=False, comment="文件名")
    version = Column(Integer, nullable=False, comment="版本号")
    box_data = Column(Text, nullable=False, comment="标注框数据(YOLO格式)")
    box_count = Column(Integer, default=0, comment="标注框数量")
    snapshot_type = Column(String(16), default="auto", comment="快照类型: auto/manual/restore")
    create_by = Column(String(64), comment="创建人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
