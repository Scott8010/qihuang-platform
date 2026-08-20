"""
岐黄智脑商业化平台 - 数据库配置
开发阶段使用 SQLite，生产通过 QH_DATABASE_URL 环境变量切换 PostgreSQL
"""
import os
from sqlalchemy import create_engine, text
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
    _migrate_living_columns()
    _migrate_template_center_columns()


def _migrate_living_columns():
    """活态化 B 架构预留：为已有 kg_feedback 表增补 source / business_weight 列。

    create_all 不会为已存在的表追加新列，故用 ALTER TABLE 显式补齐。
    PostgreSQL 用 IF NOT EXISTS 幂等；SQLite 等不支持该语法则静默跳过（不影响启动）。
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE kg_feedback ADD COLUMN IF NOT EXISTS "
                "source VARCHAR(20) NOT NULL DEFAULT 'user'"
            ))
            conn.execute(text(
                "ALTER TABLE kg_feedback ADD COLUMN IF NOT EXISTS "
                "business_weight DOUBLE PRECISION NOT NULL DEFAULT 0.0"
            ))
            conn.execute(text(
                "ALTER TABLE kg_feedback ALTER COLUMN kg_id TYPE VARCHAR(100)"
            ))
            conn.execute(text(
                "ALTER TABLE kg_feedback ADD COLUMN IF NOT EXISTS "
                "entity_name VARCHAR(100)"
            ))
            conn.execute(text(
                "ALTER TABLE kg_feedback ADD COLUMN IF NOT EXISTS "
                "entity_type VARCHAR(20)"
            ))
    except Exception as e:  # 迁移失败不应阻断平台启动
        print("WARN: kg_feedback migration skipped:", e)


def _migrate_template_center_columns():
    """能力中心二期：为已有 db_template 表增补 parent_template_id 血缘列。

    create_all 不会为已存在的表追加新列，故 PG 用 ALTER TABLE 显式补齐；
    SQLite 不支持 ADD COLUMN IF NOT EXISTS，且新表已由 create_all 创建好，故静默跳过。
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE db_template ADD COLUMN IF NOT EXISTS "
                "parent_template_id VARCHAR(36)"
            ))
    except Exception as e:  # 迁移失败不应阻断平台启动
        print("WARN: db_template migration skipped:", e)
