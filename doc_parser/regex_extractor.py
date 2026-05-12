"""
正则提取模块 - 针对结构化字段的规则提取

设计思路：
- 强结构化字段（编号、日期、金额）用正则直接提取
- 半结构化字段（甲乙方）用标签锚定+范围提取
- 提供候选列表而非单值，便于后续交叉校验
"""
import re
from typing import Dict, List, Optional, Any


class ContractRegexExtractor:
    """合同字段正则提取器"""

    # 通用日期正则（支持多种格式）
    DATE_PATTERN = (
        r"(?:"
        r"\d{4}\s*[年/\-\.]\s*\d{1,2}\s*[月/\-\.]\s*\d{1,2}\s*[日号]?"  # 2024年1月1日 / 2024-01-01
        r"|\d{4}\s*[/\-\.]\s*\d{1,2}\s*[/\-\.]\s*\d{1,2}"
        r")"
    )

    # 金额正则（中文/阿拉伯数字）
    AMOUNT_PATTERN = (
        r"(?:人民币\s*)?"
        r"(?:￥|¥|RMB\s*)?"
        r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
        r"\s*(?:元整?|圆整?|万元|亿元)?"
    )

    # 中文大写金额
    CHINESE_AMOUNT_PATTERN = r"[零壹贰叁肆伍陆柒捌玖拾佰仟万亿]{2,}[元圆][整正]?"

    def extract_all(self, text: str) -> Dict[str, Any]:
        """
        提取所有合同字段的正则候选

        Returns:
            {
                "contract_number": {"values": [...], "confidence": 0.9},
                ...
            }
        """
        return {
            "contract_number": self.extract_contract_number(text),
            "sign_date": self.extract_sign_date(text),
            "total_amount": self.extract_total_amount(text),
            "party_a": self.extract_party(text, "甲"),
            "party_b": self.extract_party(text, "乙"),
            "contract_name": self.extract_contract_name(text),
            "performance_period": self.extract_performance_period(text),
        }

    def extract_contract_number(self, text: str) -> Dict[str, Any]:
        """
        提取合同编号

        常见模式：
        - 合同编号：XXX-2024-001
        - 合同号：XXX
        - Contract No.: XXX
        """
        patterns = [
            r"合同\s*编\s*号\s*[:：]\s*([A-Za-z0-9\-_/（）()\u4e00-\u9fa5]{4,40})",
            r"合\s*同\s*号\s*[:：]\s*([A-Za-z0-9\-_/（）()\u4e00-\u9fa5]{4,40})",
            r"编\s*号\s*[:：]\s*([A-Za-z0-9\-_/]{4,40})",
            r"Contract\s*(?:No\.?|Number)\s*[:：]?\s*([A-Za-z0-9\-_/]{4,40})",
        ]

        values = []
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                val = m.group(1).strip().rstrip("，。,.；;")
                if val and val not in values:
                    values.append(val)

        return {
            "values": values,
            "confidence": 0.9 if values else 0.0,
            "source": "regex",
        }

    def extract_sign_date(self, text: str) -> Dict[str, Any]:
        """
        提取签订日期

        优先匹配"签订日期"/"签署日期"/"签订于"等关键词附近的日期
        """
        values = []

        # 带关键词的日期（高置信度）
        keyword_patterns = [
            r"(?:签订|签署|签约|订立|订于|签定)\s*(?:日期|时间|于)?\s*[:：]?\s*(" + self.DATE_PATTERN + r")",
            r"(?:日期|时间)\s*[:：]\s*(" + self.DATE_PATTERN + r")",
        ]

        for pat in keyword_patterns:
            for m in re.finditer(pat, text):
                val = self._normalize_date(m.group(1))
                if val and val not in values:
                    values.append(val)

        # 如果没有命中关键词，回退到所有日期（低置信度）
        if not values:
            all_dates = re.findall(self.DATE_PATTERN, text)
            values = [self._normalize_date(d) for d in all_dates[:3]]
            values = [v for v in values if v]
            return {
                "values": values,
                "confidence": 0.4 if values else 0.0,
                "source": "regex",
            }

        return {
            "values": values,
            "confidence": 0.85,
            "source": "regex",
        }

    def extract_total_amount(self, text: str) -> Dict[str, Any]:
        """
        提取合同金额

        优先级：
        1. "合同总价"/"合同总金额" 关键字附近的金额（最高优先级）
        2. "合计"列中的金额
        3. 其他金额关键字
        """
        values = []

        # 第一优先级：合同总价/总金额（最可靠）
        top_patterns = [
            r"合同\s*总\s*价\s*(?:人民币)?\s*[:：]?\s*(?:￥|¥|RMB)?\s*([\d,，]+(?:\.\d+)?)\s*(?:元整?|圆整?|万元|亿元)?",
            r"合同\s*(?:总)?金额\s*(?:人民币)?\s*[:：]?\s*(?:￥|¥|RMB)?\s*([\d,，]+(?:\.\d+)?)\s*(?:元整?|圆整?|万元|亿元)?",
            r"总\s*价\s*(?:人民币)?\s*[:：]\s*(?:￥|¥|RMB)?\s*([\d,，]+(?:\.\d+)?)\s*(?:元整?|圆整?|万元|亿元)?",
        ]

        for pat in top_patterns:
            for m in re.finditer(pat, text):
                val = m.group(1).strip().replace("，", ",")
                if val and val not in values:
                    values.append(val)

        # 如果第一优先级命中了，直接返回（高置信度）
        if values:
            return {
                "values": values,
                "confidence": 0.95,
                "source": "regex",
            }

        # 第二优先级：合计金额
        total_patterns = [
            r"合\s*计\s*[（(]?元?[)）]?\s*[:：]?\s*(?:￥|¥)?\s*([\d,，]+(?:\.\d+)?)",
            r"(?:￥|¥)\s*([\d,，]+(?:\.\d+)?)\s*元?\s*[（(]\s*大写",
        ]

        for pat in total_patterns:
            for m in re.finditer(pat, text):
                val = m.group(1).strip().replace("，", ",")
                if val and val not in values:
                    values.append(val)

        if values:
            return {
                "values": values,
                "confidence": 0.85,
                "source": "regex",
            }

        # 第三优先级：一般金额关键字
        keyword_patterns = [
            r"(?:金额|价款)\s*[:：]\s*((?:人民币\s*)?(?:￥|¥|RMB\s*)?[\d,，]+(?:\.\d+)?\s*(?:元整?|圆整?|万元|亿元)?)",
            r"(?:￥|¥)\s*([\d,，]+(?:\.\d+)?\s*(?:元整?|圆整?|万元|亿元)?)",
        ]

        for pat in keyword_patterns:
            for m in re.finditer(pat, text):
                val = m.group(1).strip()
                val = re.sub(r"\s+", "", val)
                val = val.replace("，", ",")
                if val and val not in values:
                    values.append(val)

        # 中文大写金额（作为辅助参考）
        for m in re.finditer(self.CHINESE_AMOUNT_PATTERN, text):
            val = m.group(0)
            if val not in values:
                values.append(val)

        return {
            "values": values,
            "confidence": 0.7 if values else 0.0,
            "source": "regex",
        }

    def extract_party(self, text: str, party_char: str) -> Dict[str, Any]:
        """
        提取甲方/乙方

        Args:
            party_char: "甲" 或 "乙"
        """
        patterns = [
            # 甲方（全称）：XXX公司
            rf"{party_char}\s*方\s*(?:[（(][^)）]*[)）])?\s*[:：]\s*([^\n，,；;]{{2,60}})",
            # 甲方：XXX
            rf"{party_char}\s*方\s*[:：]\s*([^\n，,；;]{{2,60}})",
        ]

        values = []
        for pat in patterns:
            for m in re.finditer(pat, text):
                val = m.group(1).strip()
                # 清理尾部可能的标点
                val = re.sub(r"[（(][^)）]*$", "", val).strip()
                val = val.rstrip("，。,.；;、 ")
                if val and len(val) >= 2 and val not in values:
                    values.append(val)

        return {
            "values": values,
            "confidence": 0.8 if values else 0.0,
            "source": "regex",
        }

    def extract_contract_name(self, text: str) -> Dict[str, Any]:
        """
        提取合同名称/项目名称

        优先级：
        1. "项目名称："标签后的内容（政府采购合同常见）
        2. 正文中的合同标题（如"技术开发合同书"）
        3. 封面标题（最低优先级，容易是通用模板名）

        过滤规则：
        - 排除通用封面标题（如"政府采购合同书"、"合同书"）
        - 排除过短的匹配
        """
        values = []

        # 通用/模板标题黑名单（这些不是真正的合同名称）
        blacklist = [
            "合同书", "合同", "协议书", "协议",
            "政府采购合同书", "政府采购合同",
            "采购合同书", "采购合同",
            "云南省政府采购合同书", "云南省政府采购",
        ]

        # 第一优先级：项目名称标签
        project_patterns = [
            r"项\s*目\s*名\s*称\s*[:：]\s*([^\n]{4,100})",
            r"采购\s*(?:项目|服务)\s*名\s*称\s*[:：]\s*([^\n]{4,100})",
            r"工程\s*名\s*称\s*[:：]\s*([^\n]{4,100})",
        ]
        for pat in project_patterns:
            m = re.search(pat, text)
            if m:
                val = m.group(1).strip()
                val = re.sub(r"[。；;].*$", "", val)  # 截到句号
                val = val.rstrip("，,、 ")
                if val and len(val) >= 4 and val not in blacklist:
                    values.append(val)

        # 第二优先级：正文中的合同标题（跳过前100字符的封面区域）
        body = text[100:] if len(text) > 100 else text
        title_patterns = [
            # "技术开发合同书"、"服务采购合同" 等
            r"([\u4e00-\u9fa5]{2,30}(?:合同书|合同|协议书|协议))\s*\n",
        ]
        for pat in title_patterns:
            for m in re.finditer(pat, body):
                val = m.group(1).strip()
                if val and val not in blacklist and val not in values and len(val) >= 4:
                    values.append(val)

        # 第三优先级：合同名称标签
        m = re.search(r"合同\s*名\s*称\s*[:：]\s*([^\n，,；;]{2,60})", text)
        if m:
            val = m.group(1).strip()
            if val and val not in blacklist and val not in values:
                values.append(val)

        # 第四优先级：文档开头的标题（最低优先级）
        head = text[:300]
        for m in re.finditer(r"([\u4e00-\u9fa5（）()A-Za-z0-9]{4,40}(?:合同|协议|协议书|合同书))", head):
            val = m.group(1).strip()
            if val and val not in blacklist and val not in values and not val.startswith(("本", "该", "此")):
                values.append(val)

        return {
            "values": values[:3],
            "confidence": 0.8 if values else 0.0,
            "source": "regex",
        }

    def extract_performance_period(self, text: str) -> Dict[str, Any]:
        """
        提取履行期限/交付周期

        模式：
        - 自XXXX年XX月XX日起至XXXX年XX月XX日止
        - XXXX-XX-XX 至 XXXX-XX-XX
        - 履行期限：XXX
        - 交付周期：合同签订后XX日历天
        """
        values = []

        # 日期范围模式
        range_patterns = [
            # 自...至...
            r"自\s*(" + self.DATE_PATTERN + r")\s*(?:起)?\s*(?:至|到)\s*(" + self.DATE_PATTERN + r")\s*(?:止)?",
            # 从...到...
            r"从\s*(" + self.DATE_PATTERN + r")\s*(?:到|至)\s*(" + self.DATE_PATTERN + r")",
            # X日至Y日
            r"(" + self.DATE_PATTERN + r")\s*(?:至|到|—|-|~)\s*(" + self.DATE_PATTERN + r")",
        ]

        for pat in range_patterns:
            for m in re.finditer(pat, text):
                start = self._normalize_date(m.group(1))
                end = self._normalize_date(m.group(2))
                if start and end:
                    val = f"{start} 至 {end}"
                    if val not in values:
                        values.append(val)

        # 关键词+内容模式（支持更多表述）
        keyword_patterns = [
            r"(?:交付\s*周期|履行\s*期限|服务\s*期限|合同\s*期限|有效\s*期限?|工期|建设\s*周期)\s*[:：]\s*([^\n。]{5,150})",
            # "合同签订后XX日历天" 模式
            r"(合同签订后\s*\d+\s*(?:日历天|个?工作日|天|日)[^\n。]{0,60})",
        ]

        for pat in keyword_patterns:
            m = re.search(pat, text)
            if m:
                val = m.group(1).strip()
                val = re.sub(r"[。；;].*$", "", val)  # 截到第一个句号/分号
                if val and val not in values:
                    values.insert(0, val)  # 带关键词的优先

        return {
            "values": values,
            "confidence": 0.75 if values else 0.0,
            "source": "regex",
        }

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """规范化日期格式为 YYYY-MM-DD"""
        if not date_str:
            return None
        # 提取年月日
        m = re.search(r"(\d{4})\s*[年/\-\.]\s*(\d{1,2})\s*[月/\-\.]\s*(\d{1,2})", date_str)
        if not m:
            return None
        year, month, day = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{year}-{month}-{day}"


class FieldValidator:
    """字段格式验证器 - 用于验证LLM输出的格式正确性"""

    @staticmethod
    def is_valid_date(value: str) -> bool:
        """验证日期格式"""
        if not value:
            return False
        patterns = [
            r"^\d{4}[-/\.年]\d{1,2}[-/\.月]\d{1,2}[日号]?$",
            r"^\d{4}-\d{2}-\d{2}$",
        ]
        return any(re.match(p, value.strip()) for p in patterns)

    @staticmethod
    def is_valid_amount(value: str) -> bool:
        """验证金额格式"""
        if not value:
            return False
        # 阿拉伯数字金额
        if re.search(r"\d+(?:\.\d+)?", value):
            return True
        # 中文大写金额
        if re.search(r"[零壹贰叁肆伍陆柒捌玖]", value):
            return True
        return False

    @staticmethod
    def is_valid_contract_number(value: str) -> bool:
        """验证合同编号格式（至少4字符，含字母数字）"""
        if not value or len(value) < 4:
            return False
        return bool(re.search(r"[A-Za-z0-9]", value))

    @staticmethod
    def is_valid_party(value: str) -> bool:
        """验证甲乙方名称（至少2字符，不应全是数字）"""
        if not value or len(value) < 2:
            return False
        if value.isdigit():
            return False
        return True

    @classmethod
    def validate(cls, field: str, value: Any) -> bool:
        """根据字段类型验证值"""
        if value is None or value == "":
            return False
        value_str = str(value)

        validators = {
            "sign_date": cls.is_valid_date,
            "total_amount": cls.is_valid_amount,
            "contract_number": cls.is_valid_contract_number,
            "party_a": cls.is_valid_party,
            "party_b": cls.is_valid_party,
        }

        validator = validators.get(field)
        if validator:
            return validator(value_str)
        return len(value_str.strip()) >= 2
