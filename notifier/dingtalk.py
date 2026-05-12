"""
钉钉 Webhook 推送客户端

支持：
- Markdown 格式消息
- 签名验证（加签模式）
- 发送日志记录
"""
import time
import hmac
import hashlib
import base64
import urllib.parse
import logging
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)


class DingTalkClient:
    """钉钉自定义机器人 Webhook 客户端"""

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        """
        Args:
            webhook_url: 钉钉机器人 Webhook 地址
            secret: 加签密钥（如果机器人配置了加签验证）
        """
        self._webhook_url = webhook_url
        self._secret = secret

    def _get_signed_url(self) -> str:
        """生成带签名的URL（加签模式）"""
        if not self._secret:
            return self._webhook_url

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self._secret}"
        hmac_code = hmac.new(
            self._secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return f"{self._webhook_url}&timestamp={timestamp}&sign={sign}"

    def send_markdown(
        self,
        title: str,
        content: str,
        at_mobiles: Optional[list] = None,
        at_all: bool = False,
    ) -> Dict[str, Any]:
        """
        发送 Markdown 格式消息

        Args:
            title: 消息标题（通知栏显示）
            content: Markdown 正文
            at_mobiles: @指定手机号列表
            at_all: 是否@所有人

        Returns:
            {"success": True/False, "response": {...}}
        """
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": content,
            },
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": at_all,
            },
        }
        return self._send(payload)

    def send_text(
        self,
        content: str,
        at_mobiles: Optional[list] = None,
        at_all: bool = False,
    ) -> Dict[str, Any]:
        """发送纯文本消息"""
        payload = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": at_all,
            },
        }
        return self._send(payload)

    def _send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """发送请求到钉钉"""
        url = self._get_signed_url()

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=payload)
                data = resp.json()

            if data.get("errcode") == 0:
                logger.info(f"钉钉推送成功: {payload.get('markdown', {}).get('title', '')}")
                return {"success": True, "response": data}
            else:
                logger.error(f"钉钉推送失败: {data}")
                return {"success": False, "response": data}

        except Exception as e:
            logger.exception(f"钉钉推送异常: {e}")
            return {"success": False, "response": {"error": str(e)}}


def build_schedule_message(
    contract_name: str,
    event_name: str,
    event_date: str,
    days_remaining: int,
    amount: Optional[float] = None,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    构建时间节点提醒的 Markdown 消息

    Returns:
        Markdown 格式的消息正文
    """
    # 紧急程度标识
    if days_remaining <= 0:
        urgency = "🚨 **已逾期**"
    elif days_remaining <= 3:
        urgency = "⚠️ **紧急**"
    elif days_remaining <= 7:
        urgency = "📢 **即将到期**"
    else:
        urgency = "📅 **提醒**"

    lines = [
        f"## {urgency} 合同节点提醒",
        "",
        f"**合同：** {contract_name}",
        f"**节点：** {event_name}",
        f"**日期：** {event_date}（{'已逾期' + str(abs(days_remaining)) + '天' if days_remaining <= 0 else '还剩 ' + str(days_remaining) + ' 天'}）",
    ]

    if amount:
        lines.append(f"**金额：** ¥{amount:,.2f}")
    if party_a:
        lines.append(f"**甲方：** {party_a}")
    if party_b:
        lines.append(f"**乙方：** {party_b}")
    if description:
        lines.append(f"")
        lines.append(f"> {description}")

    lines.append("")
    lines.append("---")
    lines.append("请相关人员关注并及时处理。")

    return "\n".join(lines)
