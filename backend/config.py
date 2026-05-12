"""
后端配置
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 存储目录
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
STORAGE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

# 数据库配置
DB_PATH = STORAGE_DIR / "parser.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# 上传文件配置
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

# API配置
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# 任务队列配置
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))  # 并发解析任务数
