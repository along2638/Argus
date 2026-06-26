from sqlalchemy import Column, BigInteger, String, Text, Float, Integer, DateTime, func
from app.db import Base


class AlarmRecord(Base):
    __tablename__ = "alarm_record"
    __table_args__ = {"comment": "告警记录表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    stream_url = Column(Text, nullable=False, comment="监控流地址")
    stream_id = Column(String(64), comment="流标识符")
    alarm_type = Column(String(32), nullable=False, comment="告警类型: helmet/fire/intrusion")
    confidence = Column(Float, nullable=False, comment="检测置信度")
    image_path = Column(Text, nullable=False, comment="告警图片路径(MinIO)")
    track_id = Column(Integer, comment="目标跟踪ID")
    class_name = Column(String(64), comment="检测类别名称")
    detected_at = Column(DateTime, nullable=False, server_default=func.now(), comment="检测时间")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
