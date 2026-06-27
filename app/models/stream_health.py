"""Stream health snapshot model — periodic recording of per-stream metrics."""

from sqlalchemy import Column, BigInteger, String, Float, Integer, DateTime, func
from app.db import Base


class StreamHealth(Base):
    __tablename__ = "stream_health"
    __table_args__ = {"comment": "流健康度快照表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    stream_id = Column(String(64), nullable=False, index=True)
    status = Column(String(16), nullable=False, comment="running/error/reconnecting/stopped")
    fps = Column(Float, default=0, comment="当前帧率")
    alarm_count = Column(Integer, default=0, comment="累计告警数")
    error_count = Column(Integer, default=0, comment="连续错误次数")
    error_message = Column(String(512), comment="最近错误信息")
    recorded_at = Column(DateTime, nullable=False, server_default=func.now(), comment="采样时间")
