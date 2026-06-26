from sqlalchemy import Column, BigInteger, String, Text, Integer, Boolean, DateTime, func
from app.db import Base


class AnnotationImage(Base):
    __tablename__ = "annotation_image"
    __table_args__ = {"comment": "标注图片表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    filename = Column(String(255), nullable=False, comment="原始文件名")
    file_path = Column(Text, nullable=False, comment="存储路径")
    file_size = Column(Integer, comment="文件大小(字节)")
    width = Column(Integer, comment="图片宽度(像素)")
    height = Column(Integer, comment="图片高度(像素)")
    source = Column(String(32), default="upload", comment="来源: upload/capture/url")
    dataset_name = Column(String(128), comment="所属数据集名称")
    split = Column(String(16), default="train", comment="数据集划分: train/val/test")
    is_annotated = Column(Boolean, default=False, comment="是否已标注")
    box_count = Column(Integer, default=0, comment="标注框数量")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
