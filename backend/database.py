"""
数据库连接管理
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

# SQLite需要特殊参数允许多线程
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,  # 等待锁释放最多30秒
    },
    echo=False,
    pool_size=5,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    SQLite连接时设置WAL模式和其他优化参数
    WAL模式允许读写并发，大幅减少 database is locked 错误
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")  # 30秒等待
    cursor.execute("PRAGMA cache_size=-64000")   # 64MB缓存
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI依赖注入用的session生成器"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表结构"""
    from . import models  # noqa: F401 确保模型被注册
    Base.metadata.create_all(bind=engine)
