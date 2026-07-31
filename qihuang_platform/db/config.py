"""
岐黄智脑商业化平台 - 数据库配置
开发阶段使用 SQLite，生产通过 QH_DATABASE_URL 环境变量切换 PostgreSQL
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "QH_DATABASE_URL",
    "sqlite:///./qihuang_platform.db"
)

# PostgreSQL 连接格式: postgresql://user:pass@host:5432/dbname
IS_SQLITE = "sqlite" in DATABASE_URL

engine_kwargs = {"echo": False}

if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    # SQLite 用 StaticPool（避免多线程写锁）
    from sqlalchemy.pool import StaticPool
    engine_kwargs["poolclass"] = StaticPool
else:
    # PostgreSQL 用默认 QueuePool（支持并发连接）
    engine_kwargs["pool_size"] = int(os.getenv("QH_DB_POOL_SIZE", "10"))
    engine_kwargs["max_overflow"] = int(os.getenv("QH_DB_MAX_OVERFLOW", "20"))
    engine_kwargs["pool_pre_ping"] = True  # 自动检测断开连接

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """获取数据库会话（FastAPI 依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表（开发/首次部署时调用）"""
    Base.metadata.create_all(bind=engine)
