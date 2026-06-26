from sqlalchemy import Column, BigInteger, String, DateTime, JSON, func
from app.db import Base


class OperationLog(Base):
    __tablename__ = "operation_log"
    __table_args__ = {"comment": "操作日志表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    user_id = Column(BigInteger, comment="操作用户ID")
    username = Column(String(64), comment="用户名")
    action = Column(String(64), nullable=False, comment="操作类型: login/start_stream/detect等")
    target_type = Column(String(32), comment="操作对象类型")
    target_id = Column(String(64), comment="操作对象ID")
    detail = Column(JSON, comment="操作详情")
    ip_address = Column(String(64), comment="客户端IP")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
