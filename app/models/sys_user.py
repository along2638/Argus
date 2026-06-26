from sqlalchemy import Column, BigInteger, String, Text, Boolean, DateTime, func
from app.db import Base


class SysUser(Base):
    __tablename__ = "sys_user"
    __table_args__ = {"comment": "用户表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    username = Column(String(64), nullable=False, unique=True, comment="用户名")
    password_hash = Column(Text, nullable=False, comment="密码哈希(PBKDF2-SHA256)")
    display_name = Column(String(128), comment="显示名称")
    role = Column(String(16), default="viewer", comment="角色: admin/operator/annotator/viewer")
    is_active = Column(Boolean, default=True, comment="是否启用")
    last_login = Column(DateTime, comment="最后登录时间")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")
