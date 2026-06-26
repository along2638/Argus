from sqlalchemy import Column, BigInteger, String, DateTime, func
from app.db import Base


class SysSession(Base):
    __tablename__ = "sys_session"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    token = Column(String(128), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    create_time = Column(DateTime, nullable=False, server_default=func.now())
