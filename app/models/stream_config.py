from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, JSON, func
from app.db import Base


class StreamConfig(Base):
    __tablename__ = "stream_config"
    __table_args__ = {"comment": "监控流配置表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    stream_id = Column(String(64), nullable=False, unique=True, comment="流唯一标识")
    stream_url = Column(Text, nullable=False, comment="流地址(RTSP/RTMP)")
    alarm_types = Column(JSON, nullable=False, comment="检测类型列表")
    status = Column(String(16), default="idle", comment="状态: idle/running/reconnecting/error/stopped")
    error_message = Column(Text, comment="错误信息")
    frame_count = Column(Integer, default=0, comment="已处理帧数")
    alarm_count = Column(Integer, default=0, comment="告警次数")
    started_at = Column(DateTime, comment="启动时间")
    stopped_at = Column(DateTime, comment="停止时间")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
