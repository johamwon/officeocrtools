"""
时间节点派生模块

从合同字段中派生出需要提醒的时间节点：
- 付款节点（签订后N天、验收后N天）
- 交付截止日
- 质保到期日
- 履约保证金退还
"""
import re
import logging
from datetime import date, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ScheduleExtractor:
    """从合同字段派生时间节点"""

    def extract_schedules(
        self,
        contract_id: int,
        fields: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        从合同字段派生所有时间节点

        Args:
            contract_id: 合同ID
            fields: 合同字段字典

        Returns:
            时间节点列表，每个元素包含:
            - contract_id
            - event_type
            - event_name
            - event_date
            - amount (可选)
            - description
            - remind_days
        """
        schedules = []

        sign_date = self._parse_date(fields.get("sign_date"))
        total_amount = self._parse_amount(fields.get("total_amount"))

        # 1. 交付截止日
        delivery = self._extract_delivery_deadline(fields, sign_date)
        if delivery:
            delivery["contract_id"] = contract_id
            schedules.append(delivery)

        # 2. 付款节点
        payment_schedules = self._extract_payment_schedules(
            fields, sign_date, total_amount
        )
        for ps in payment_schedules:
            ps["contract_id"] = contract_id
            schedules.append(ps)

        # 3. 质保到期
        warranty = self._extract_warranty_end(fields, delivery)
        if warranty:
            warranty["contract_id"] = contract_id
            schedules.append(warranty)

        logger.info(f"合同 {contract_id} 派生出 {len(schedules)} 个时间节点")
        return schedules

    def _extract_delivery_deadline(
        self, fields: Dict[str, Any], sign_date: Optional[date]
    ) -> Optional[Dict[str, Any]]:
        """提取交付截止日"""
        period = fields.get("performance_period", "") or ""

        # 模式1：合同签订后XX日历天
        m = re.search(r"合同签订后\s*(\d+)\s*日历天", period)
        if m and sign_date:
            days = int(m.group(1))
            deadline = sign_date + timedelta(days=days)
            return {
                "event_type": "delivery",
                "event_name": "项目交付截止",
                "event_date": deadline,
                "description": f"合同签订后{days}日历天完成交付（签订日：{sign_date}）",
                "remind_days": [30, 15, 7, 3, 1],
            }

        # 模式2：合同签订后XX个工作日
        m = re.search(r"合同签订后\s*(\d+)\s*个?工作日", period)
        if m and sign_date:
            workdays = int(m.group(1))
            # 粗略估算：工作日 * 1.4 ≈ 日历天
            days = int(workdays * 1.4)
            deadline = sign_date + timedelta(days=days)
            return {
                "event_type": "delivery",
                "event_name": "项目交付截止",
                "event_date": deadline,
                "description": f"合同签订后{workdays}个工作日完成交付（约{days}日历天）",
                "remind_days": [30, 15, 7, 3, 1],
            }

        # 模式3：具体日期范围 "YYYY-MM-DD 至 YYYY-MM-DD"
        m = re.search(r"至\s*(\d{4}-\d{2}-\d{2})", period)
        if m:
            deadline = self._parse_date(m.group(1))
            if deadline:
                return {
                    "event_type": "delivery",
                    "event_name": "项目交付截止",
                    "event_date": deadline,
                    "description": f"合同约定交付截止日：{deadline}",
                    "remind_days": [30, 15, 7, 3, 1],
                }

        return None

    def _extract_payment_schedules(
        self,
        fields: Dict[str, Any],
        sign_date: Optional[date],
        total_amount: Optional[float],
    ) -> List[Dict[str, Any]]:
        """提取付款节点"""
        schedules = []
        payment_terms = fields.get("payment_terms", "") or ""

        if not payment_terms:
            return schedules

        # 先将中文数字转为阿拉伯数字
        normalized = self._normalize_chinese_numbers(payment_terms)

        # 模式1：签订后XX个工作日内支付XX%
        pattern1 = r"(?:合同)?签订后\s*(\d+)\s*个?工作日内?\s*支付\s*(?:合同价的?\s*)?(\d+)%"
        for m in re.finditer(pattern1, normalized):
            workdays = int(m.group(1))
            percent = int(m.group(2))
            if sign_date:
                days = int(workdays * 1.4)
                pay_date = sign_date + timedelta(days=days)
                amount = total_amount * percent / 100 if total_amount else None
                schedules.append({
                    "event_type": "payment",
                    "event_name": f"支付合同款{percent}%",
                    "event_date": pay_date,
                    "amount": amount,
                    "description": f"签订后{workdays}个工作日内支付{percent}%"
                                   + (f"（¥{amount:,.0f}）" if amount else ""),
                    "remind_days": [7, 3, 1],
                })

        # 模式2：验收合格后XX个工作日内支付XX%
        pattern2 = r"验收合格后\s*(\d+)\s*个?工作日内?\s*支付\s*(?:剩余的?\s*)?(\d+)%"
        for m in re.finditer(pattern2, normalized):
            workdays = int(m.group(1))
            percent = int(m.group(2))
            amount = total_amount * percent / 100 if total_amount else None
            # 验收日期未知，用交付截止日估算
            schedules.append({
                "event_type": "payment",
                "event_name": f"验收后支付尾款{percent}%",
                "event_date": None,  # 需要验收后手动设置
                "amount": amount,
                "description": f"验收合格后{workdays}个工作日内支付{percent}%"
                               + (f"（¥{amount:,.0f}）" if amount else "")
                               + "（待验收后确认日期）",
                "remind_days": [7, 3, 1],
            })

        # 模式3：直接金额 ¥XXX
        if not schedules:
            # 回退：如果没有匹配到百分比模式，尝试提取金额
            amounts = re.findall(r"[¥￥]\s*([\d,]+)", payment_terms)
            if amounts and sign_date:
                first_amount = float(amounts[0].replace(",", ""))
                schedules.append({
                    "event_type": "payment",
                    "event_name": "首笔付款",
                    "event_date": sign_date + timedelta(days=21),
                    "amount": first_amount,
                    "description": f"首笔付款 ¥{first_amount:,.0f}",
                    "remind_days": [7, 3, 1],
                })

        return schedules

    def _normalize_chinese_numbers(self, text: str) -> str:
        """将中文数字转为阿拉伯数字（常见的合同用语）"""
        cn_map = {
            "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
            "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
            "十一": "11", "十二": "12", "十三": "13", "十四": "14", "十五": "15",
            "十六": "16", "十七": "17", "十八": "18", "十九": "19", "二十": "20",
            "三十": "30", "四十": "40", "五十": "50", "六十": "60",
            "九十": "90",
        }
        # 按长度降序替换（先替换"十五"再替换"十"和"五"）
        for cn, num in sorted(cn_map.items(), key=lambda x: -len(x[0])):
            text = text.replace(cn, num)
        return text

    def _extract_warranty_end(
        self, fields: Dict[str, Any], delivery_schedule: Optional[Dict]
    ) -> Optional[Dict[str, Any]]:
        """提取质保到期日"""
        # 从服务内容或付款条件中查找质保期
        all_text = " ".join(str(v) for v in fields.values() if v)

        # 匹配 "一年免费质保" / "质保期一年" / "12个月质保"
        m = re.search(r"(?:质保期?|保修期?)\s*(?:为)?\s*(\d+)\s*(?:年|个月)", all_text)
        if not m:
            m = re.search(r"(\d+)\s*年\s*(?:免费)?质保", all_text)

        if m:
            num = int(m.group(1))
            # 判断是年还是月
            if "月" in m.group(0):
                months = num
            else:
                months = num * 12

            # 质保从交付/验收日开始
            if delivery_schedule and delivery_schedule.get("event_date"):
                start = delivery_schedule["event_date"]
                # 粗略计算月数
                warranty_end = date(
                    start.year + months // 12,
                    start.month + months % 12 if start.month + months % 12 <= 12
                    else (start.month + months % 12) - 12,
                    start.day,
                )
                if start.month + months % 12 > 12:
                    warranty_end = warranty_end.replace(year=warranty_end.year + 1)

                return {
                    "event_type": "warranty",
                    "event_name": "质保到期",
                    "event_date": warranty_end,
                    "description": f"免费质保期{num}{'个月' if '月' in m.group(0) else '年'}，到期日：{warranty_end}",
                    "remind_days": [30, 15, 7],
                }

        return None

    def _parse_date(self, value: Any) -> Optional[date]:
        """解析日期字符串为date对象"""
        if not value:
            return None
        if isinstance(value, date):
            return value
        s = str(value).strip()
        m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", s)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
        return None

    def _parse_amount(self, value: Any) -> Optional[float]:
        """解析金额"""
        if not value:
            return None
        s = str(value).replace(",", "").replace("，", "")
        m = re.search(r"([\d.]+)", s)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
        return None
