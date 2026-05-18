"""
付款条件结构化解析器

将合同中的付款条件文本解析为结构化的时间节点列表。

输出格式：
[
    {
        "stage": "首付款",
        "trigger": "合同签订后15个工作日内",
        "percentage": 90,
        "amount": 378000,
        "condition": "合同签订",
        "description": "合同签订后十五个工作日内支付合同价的90%"
    },
    {
        "stage": "尾款",
        "trigger": "验收合格后15个工作日内",
        "percentage": 10,
        "amount": 42000,
        "condition": "验收合格",
        "description": "验收合格后十五个工作日内支付剩余的10%"
    }
]
"""
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 中文数字映射
CN_NUM_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
    "二十五": 25, "三十": 30, "四十五": 45, "六十": 60, "九十": 90,
}


class PaymentParser:
    """付款条件结构化解析器"""

    def parse(
        self, payment_text: str, total_amount: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        解析付款条件文本为结构化节点列表

        Args:
            payment_text: 付款条件原文
            total_amount: 合同总金额（用于计算百分比对应金额）

        Returns:
            付款节点列表
        """
        if not payment_text:
            return []

        # 先将中文数字转为阿拉伯数字
        normalized = self._normalize_chinese_numbers(payment_text)

        schedules = []

        # 模式1：百分比付款（最常见）
        # "签订后XX工作日内支付XX%"
        # "验收合格后XX工作日内支付XX%"
        schedules.extend(self._extract_percentage_payments(normalized, total_amount))

        # 模式2：固定金额付款
        # "支付人民币XXX元"
        if not schedules:
            schedules.extend(self._extract_fixed_payments(normalized))

        # 模式3：分期付款（第一期/第二期...）
        if not schedules:
            schedules.extend(self._extract_installment_payments(normalized, total_amount))

        # 补充：提取履约保证金
        deposit = self._extract_deposit(normalized)
        if deposit:
            schedules.append(deposit)

        # 按阶段排序
        stage_order = {"预付款": 0, "首付款": 1, "第一期": 1, "第二期": 2, "第三期": 3, "尾款": 8, "质保金": 9, "履约保证金": -1}
        schedules.sort(key=lambda x: stage_order.get(x.get("stage", ""), 5))

        logger.info(f"付款条件解析出 {len(schedules)} 个节点")
        return schedules

    def _extract_percentage_payments(
        self, text: str, total_amount: Optional[float]
    ) -> List[Dict[str, Any]]:
        """提取百分比付款节点"""
        results = []

        # 通用模式：[触发条件]XX个工作日/日历天内支付[合同价的]XX%
        patterns = [
            # 合同签订后XX个工作日内支付XX%
            (
                r"(?:合同)?签订后\s*(\d+)\s*个?(?:工作日|日历天|天)内?\s*支付\s*(?:合同(?:价|金额)的?\s*)?(\d+)%",
                "合同签订",
                "首付款",
            ),
            # 预付款/预付XX%
            (
                r"(?:预付款?|预付)\s*(?:为?\s*)?(?:合同(?:价|金额)的?\s*)?(\d+)%",
                "合同签订",
                "预付款",
            ),
            # 验收合格后XX个工作日内支付XX%
            (
                r"验收合格后\s*(\d+)\s*个?(?:工作日|日历天|天)内?\s*支付\s*(?:剩余的?\s*)?(\d+)%",
                "验收合格",
                "尾款",
            ),
            # 到货/交付后XX天内支付XX%
            (
                r"(?:到货|交付|交货)后\s*(\d+)\s*个?(?:工作日|日历天|天)内?\s*支付\s*(?:合同(?:价|金额)的?\s*)?(\d+)%",
                "交付完成",
                "交付款",
            ),
            # 试运行/上线后XX天支付XX%
            (
                r"(?:试运行|上线|投产)后?\s*(\d+)\s*个?(?:工作日|日历天|天)内?\s*支付\s*(\d+)%",
                "试运行",
                "试运行款",
            ),
            # 质保期满后支付XX%
            (
                r"质保期?满后?\s*(?:\d+\s*个?(?:工作日|日历天|天)内?\s*)?支付\s*(?:剩余的?\s*)?(\d+)%",
                "质保期满",
                "质保金",
            ),
        ]

        for pattern, condition, stage in patterns:
            for m in re.finditer(pattern, text):
                groups = m.groups()
                if len(groups) == 2:
                    days = int(groups[0])
                    percentage = int(groups[1])
                    trigger = f"{condition}后{days}个工作日内"
                elif len(groups) == 1:
                    # 没有天数的模式（如预付款、质保金）
                    percentage = int(groups[0])
                    days = None
                    trigger = condition
                else:
                    continue

                amount = total_amount * percentage / 100 if total_amount else None

                # 从原文中截取描述（取匹配位置前后的完整句子）
                start = m.start()
                # 向前找到句子开头（数字序号或换行）
                line_start = text.rfind("\n", max(0, start - 100), start)
                if line_start == -1:
                    line_start = max(0, start - 50)
                else:
                    line_start += 1
                # 向后找到句子结尾
                line_end = text.find("。", m.end())
                if line_end == -1 or line_end - m.end() > 100:
                    line_end = min(len(text), m.end() + 60)
                else:
                    line_end += 1
                desc = text[line_start:line_end].strip()

                results.append({
                    "stage": stage,
                    "trigger": trigger,
                    "percentage": percentage,
                    "amount": amount,
                    "days": days,
                    "condition": condition,
                    "description": desc,
                })

        return results

    def _extract_fixed_payments(self, text: str) -> List[Dict[str, Any]]:
        """提取固定金额付款"""
        results = []

        # 模式：支付/付款 人民币/¥ XXX 元
        pattern = r"(?:支付|付款)\s*(?:人民币|[¥￥])\s*([\d,]+(?:\.\d+)?)\s*元"
        for m in re.finditer(pattern, text):
            amount = float(m.group(1).replace(",", ""))
            # 尝试从上下文判断阶段
            context = text[max(0, m.start()-30):m.start()]
            if "签订" in context or "首" in context:
                stage = "首付款"
                condition = "合同签订"
            elif "验收" in context:
                stage = "尾款"
                condition = "验收合格"
            else:
                stage = f"付款{len(results)+1}"
                condition = "待确认"

            results.append({
                "stage": stage,
                "trigger": condition,
                "percentage": None,
                "amount": amount,
                "days": None,
                "condition": condition,
                "description": text[max(0, m.start()-10):min(len(text), m.end()+30)].strip(),
            })

        return results

    def _extract_installment_payments(
        self, text: str, total_amount: Optional[float]
    ) -> List[Dict[str, Any]]:
        """提取分期付款（第一期/第二期...）"""
        results = []

        pattern = r"第([一二三四五六七八九十\d]+)(?:期|笔|次)\s*[:：]?\s*(?:支付\s*)?(?:合同(?:价|金额)的?\s*)?(\d+)%"
        for m in re.finditer(pattern, text):
            stage_num = m.group(1)
            percentage = int(m.group(2))

            # 转换中文数字
            if stage_num in CN_NUM_MAP:
                num = CN_NUM_MAP[stage_num]
            else:
                try:
                    num = int(stage_num)
                except ValueError:
                    num = len(results) + 1

            amount = total_amount * percentage / 100 if total_amount else None

            results.append({
                "stage": f"第{num}期",
                "trigger": f"第{num}期付款",
                "percentage": percentage,
                "amount": amount,
                "days": None,
                "condition": f"第{num}期",
                "description": text[max(0, m.start()-5):min(len(text), m.end()+50)].strip(),
            })

        return results

    def _extract_deposit(self, text: str) -> Optional[Dict[str, Any]]:
        """提取履约保证金"""
        pattern = r"(?:履约)?保证金\s*[:：]?\s*(?:人民币|[¥￥])?\s*([\d,]+(?:\.\d+)?)\s*元"
        m = re.search(pattern, text)
        if not m:
            return None

        amount = float(m.group(1).replace(",", ""))

        # 查找退还条件
        return_condition = "服务期满"
        return_match = re.search(r"(?:服务期满|质保期满|验收合格)后.*?(?:返还|退还)", text)
        if return_match:
            return_condition = return_match.group(0)[:20]

        return {
            "stage": "履约保证金",
            "trigger": "合同签订前",
            "percentage": None,
            "amount": amount,
            "days": None,
            "condition": "合同签订前缴纳",
            "return_condition": return_condition,
            "description": f"履约保证金 ¥{amount:,.0f}，{return_condition}后退还",
        }

    def _normalize_chinese_numbers(self, text: str) -> str:
        """将中文数字转为阿拉伯数字"""
        for cn, num in sorted(CN_NUM_MAP.items(), key=lambda x: -len(x[0])):
            text = text.replace(cn, str(num))
        return text
