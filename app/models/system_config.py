from sqlalchemy import Column, BigInteger, String, Text, DateTime, func
from app.db import Base


class SystemConfig(Base):
    __tablename__ = "system_config"
    __table_args__ = {"comment": "系统配置表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    config_key = Column(String(128), nullable=False, unique=True, comment="配置键")
    config_value = Column(Text, nullable=False, comment="配置值")
    config_type = Column(String(16), default="string", comment="值类型: string/int/bool/json")
    description = Column(Text, comment="配置说明")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
