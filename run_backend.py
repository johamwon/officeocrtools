"""
启动后端服务
使用方式: python run_backend.py
"""
import os
import sys
import configparser
from pathlib import Path

# 确定基础目录
BASE_DIR = Path(__file__).resolve().parent

# 加载配置文件（优先级：config/app.ini > .env > 环境变量）
def load_config():
    """从 config/app.ini 加载配置到环境变量"""
    config_file = BASE_DIR / "config" / "app.ini"
    if not config_file.exists():
        # 回退到 .env
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        os.environ.setdefault(key.strip(), value.strip())
        return

    config = configparser.ConfigParser()
    config.read(config_file, encoding="utf-8")

    # [server]
    if config.has_section("server"):
        os.environ.setdefault("API_HOST", config.get("server", "host", fallback="0.0.0.0"))
        os.environ.setdefault("API_PORT", config.get("server", "port", fallback="8000"))

    # [llm]
    if config.has_section("llm"):
        os.environ.setdefault("LLM_BASE_URL", config.get("llm", "base_url", fallback="http://localhost:8080/v1"))
        os.environ.setdefault("LLM_API_KEY", config.get("llm", "api_key", fallback="not-needed"))
        os.environ.setdefault("LLM_MODEL", config.get("llm", "model", fallback="qwen2.5-coder-1.5b-instruct"))

    # [notify]
    if config.has_section("notify"):
        os.environ.setdefault("NOTIFY_ENABLED", config.get("notify", "enabled", fallback="false"))
        os.environ.setdefault("DINGTALK_WEBHOOK_URL", config.get("notify", "dingtalk_webhook", fallback=""))
        os.environ.setdefault("DINGTALK_SECRET", config.get("notify", "dingtalk_secret", fallback=""))
        os.environ.setdefault("NOTIFY_CHECK_HOUR", config.get("notify", "check_hour", fallback="9"))
        os.environ.setdefault("NOTIFY_CHECK_MINUTE", config.get("notify", "check_minute", fallback="0"))


if __name__ == "__main__":
    load_config()

    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
        log_level="info",
    )
