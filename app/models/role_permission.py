"""Role-Permission mapping model for RBAC."""

from sqlalchemy import Column, BigInteger, String, DateTime, func
from app.db import Base


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = {"comment": "角色权限映射表"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    role = Column(String(32), nullable=False, index=True, comment="角色名: admin/operator/annotator/viewer")
    permission = Column(String(64), nullable=False, comment="权限标识: view_stream/manage_stream/...")
    create_time = Column(DateTime, nullable=False, server_default=func.now())
