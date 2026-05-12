"""
启动后端服务
使用方式: python run_backend.py
"""
import os
from pathlib import Path

# 加载 .env 文件
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if not os.environ.get(key):  # 不覆盖已有环境变量
                    os.environ[key] = value

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
        log_level="info",
    )
