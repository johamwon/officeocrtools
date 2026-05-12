"""
推送模块配置
"""
import os

# 钉钉 Webhook 配置
DINGTALK_WEBHOOK_URL = os.getenv(
    "DINGTALK_WEBHOOK_URL",
    ""  # 需要配置你的钉钉机器人 Webhook 地址
)
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")  # 加签密钥（可选）

# 定时检查配置
NOTIFY_CHECK_HOUR = int(os.getenv("NOTIFY_CHECK_HOUR", "9"))    # 每日检查时间（小时）
NOTIFY_CHECK_MINUTE = int(os.getenv("NOTIFY_CHECK_MINUTE", "0"))  # 每日检查时间（分钟）

# 是否启用推送调度器
NOTIFY_ENABLED = os.getenv("NOTIFY_ENABLED", "false").lower() in ("true", "1", "yes")
