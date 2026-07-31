"""
岐黄智脑商业化平台 - 数据库配置
开发阶段使用 SQLite，生产切换 PostgreSQL
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv(
    "QH_DATABASE_URL",
    "sqlite:///./qihuang_platform.db"  # 开发默认 SQLite
)

# 生产 PostgreSQL 连接串格式:
# "postgresql+asyncpg://user:pass@host:5432/qihuang_platform"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    poolclass=StaticPool,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """获取数据库会话（FastAPI依赖）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表"""
    Base.metadata.create_all(bind=engine)
