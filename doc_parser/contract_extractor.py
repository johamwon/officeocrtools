"""
合同专用提取器 - 正则+LLM混合提取与交叉校验

策略：
1. 正则提取：快速获取结构化字段候选值
2. LLM提取：处理弱结构化字段（服务内容、付款条件等）
   - 弱结构化字段使用关键字定位+上下文扩展，精准送入LLM
3. 交叉校验：双方结果对比，按字段类型决定优先级
4. 输出带置信度的最终结果
"""
import re
import logging
from typing import Dict, Any, Optional, List, Tuple

from .regex_extractor import ContractRegexExtractor, FieldValidator
from .llm_extractor import LLMExtractor
from .text_processor import TextProcessor
from .schema_manager import SchemaManager
from .payment_parser import PaymentParser

logger = logging.getLogger(__name__)


# 字段分类：决定正则和LLM的优先级
FIELD_PRIORITY = {
    # 强结构化：正则优先
    "contract_number": "regex",
    "sign_date": "regex",
    "total_amount": "regex",
    # 半结构化：双向对比
    "party_a": "both",
    "party_b": "both",
    "contract_name": "both",
    "performance_period": "both",
    # 弱结构化：LLM优先（使用关键字定位上下文）
    "service_content": "llm",
    "payment_terms": "llm",
}

# 弱结构化字段的关键字配置
# 用于在全文中定位相关段落，然后扩展上下文送入LLM
FIELD_KEYWORDS = {
    "payment_terms": {
        "keywords": [
            "付款", "支付", "结算", "款项", "费用支付",
            "付款方式", "付款条件", "支付方式", "支付条件",
            "账期", "预付", "尾款", "分期", "到账",
        ],
        "expand_before": 2,
        "expand_after": 4,
        "prompt": "请从以下文本中提取付款方式和条件（包括付款比例、时间节点、付款条件），严格按JSON格式输出，不要输出其他内容:\n输出格式: {\"payment_terms\": \"...\"}",
    },
    "performance_period": {
        "keywords": [
            "履行期限", "服务期限", "合同期限", "有效期",
            "起始日期", "终止日期", "合同期", "服务期",
            "自.*起.*至.*止", "有效期限",
            "交付周期", "交付期限", "建设周期", "工期",
            "日历天", "工作日内完成",
        ],
        "expand_before": 1,
        "expand_after": 3,
        "prompt": "请从以下文本中提取履行期限或交付周期（如有具体日期写起止日期，如为天数写具体描述），严格按JSON格式输出，不要输出其他内容:\n输出格式: {\"performance_period\": \"...\"}",
    },
    "service_content": {
        "keywords": [
            "服务内容", "服务范围", "工作内容", "项目内容",
            "标的", "合同标的", "服务事项", "委托事项",
            "承包范围", "供货内容", "采购内容",
            "项目名称", "采购服务名称", "技术内容",
        ],
        "expand_before": 1,
        "expand_after": 5,
        "prompt": "请从以下文本中提取服务内容或项目标的物（简要概括主要工作），严格按JSON格式输出，不要输出其他内容:\n输出格式: {\"service_content\": \"...\"}",
    },
}


class ContractExtractor:
    """
    合同混合提取器

    流程：
    1. 正则提取所有可提取字段
    2. LLM提取：
       - 强/半结构化字段：分块送入
       - 弱结构化字段：关键字定位 → 上下文扩展 → 精准送入LLM
    3. 交叉校验合并结果
    """

    def __init__(self, llm_extractor: LLMExtractor, schema_manager: SchemaManager):
        self._regex = ContractRegexExtractor()
        self._llm = llm_extractor
        self._schema = schema_manager
        self._validator = FieldValidator()
        self._text_processor = TextProcessor()
        self._payment_parser = PaymentParser()

    def extract(
        self,
        ocr_text: str,
        fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        混合提取合同要素

        Args:
            ocr_text: 清洗后的OCR文本
            fields: 指定提取字段，None则提取全部

        Returns:
            详细提取结果（含置信度和来源）
        """
        all_fields = fields or list(self._schema.get_fields("contract").keys())

        # 1. 正则提取
        logger.info("正则提取合同字段...")
        regex_results = self._regex.extract_all(ocr_text)

        # 2. 确定哪些字段需要LLM提取
        # 正则高置信度（>=0.9）的字段跳过LLM
        llm_needed_fields = []
        for field in all_fields:
            regex_data = regex_results.get(field, {})
            regex_conf = regex_data.get("confidence", 0.0) if isinstance(regex_data, dict) else 0.0
            regex_values = regex_data.get("values", []) if isinstance(regex_data, dict) else []
            if regex_conf >= 0.9 and regex_values:
                logger.debug(f"字段 '{field}' 正则高置信度({regex_conf})，跳过LLM")
            else:
                llm_needed_fields.append(field)

        logger.info(f"需要LLM提取的字段: {llm_needed_fields}（跳过{len(all_fields) - len(llm_needed_fields)}个高置信度字段）")

        # 3. LLM提取
        llm_results = {}
        if llm_needed_fields:
            # 分离弱结构化字段和普通字段
            keyword_fields = [f for f in llm_needed_fields if f in FIELD_KEYWORDS]
            normal_fields = [f for f in llm_needed_fields if f not in FIELD_KEYWORDS]

            # 3a. 普通字段：分块提取
            if normal_fields:
                _, chunks = self._text_processor.process(ocr_text)
                llm_results = self._llm_extract_from_chunks(chunks, normal_fields)

            # 3b. 弱结构化字段：合并为一次调用（关键字定位+上下文合并）
            if keyword_fields:
                batch_results = self._batch_keyword_extract(ocr_text, keyword_fields)
                llm_results.update(batch_results)

        # 4. 交叉校验
        logger.info("交叉校验...")
        final_results = self._cross_validate(regex_results, llm_results, all_fields)

        # 5. 付款条件结构化解析
        if "payment_schedule" in all_fields or "payment_terms" in all_fields:
            payment_schedule = self._parse_payment_schedule(ocr_text, final_results)
            if payment_schedule:
                final_results["payment_schedule"] = {
                    "value": payment_schedule,
                    "confidence": 0.8,
                    "source": "structured_parser",
                    "regex_value": None,
                    "llm_value": None,
                }

        return final_results

    def _batch_keyword_extract(
        self, full_text: str, fields: List[str]
    ) -> Dict[str, Optional[str]]:
        """
        批量关键字定位提取（合并多个弱结构化字段为一次LLM调用）

        策略：
        1. 为每个字段分别定位上下文
        2. 合并所有上下文（用分隔符区分）
        3. 一次LLM调用提取所有字段
        4. 如果合并后超长，回退到逐个提取
        """
        paragraphs = self._split_paragraphs(full_text)
        if not paragraphs:
            return {f: None for f in fields}

        # 收集每个字段的上下文
        field_contexts = {}
        for field in fields:
            config = FIELD_KEYWORDS.get(field)
            if not config:
                continue
            hit_indices = self._find_keyword_hits(paragraphs, config["keywords"])
            if hit_indices:
                ctx = self._expand_context(
                    paragraphs, hit_indices,
                    config["expand_before"], config["expand_after"]
                )
                field_contexts[field] = ctx[:600]  # 每个字段最多600字符

        if not field_contexts:
            return {f: None for f in fields}

        # 合并上下文
        combined_context = ""
        for field, ctx in field_contexts.items():
            combined_context += f"[{field}相关段落]\n{ctx}\n\n"

        # 检查总长度（不超过1200字符）
        if len(combined_context) > 1200:
            # 超长：回退到逐个提取
            logger.info("合并上下文超长，回退到逐个提取")
            results = {}
            for field in fields:
                value = self._keyword_context_extract(full_text, field)
                results[field] = value
            return results

        # 构建合并prompt
        field_descs = []
        for field in field_contexts.keys():
            config = FIELD_KEYWORDS[field]
            # 从prompt中提取字段描述
            desc = config["prompt"].split("Field: ")[-1] if "Field: " in config["prompt"] else field
            field_descs.append(desc)

        fields_str = ", ".join(field_descs)
        prompt = f"""Extract fields from text, output JSON only.
Fields: {fields_str}

Text:
{combined_context}

JSON:"""

        logger.info(f"合并提取 {len(field_contexts)} 个弱结构化字段（{len(combined_context)}字符）")

        try:
            raw_output = self._llm.raw_call(prompt, stop=["\n\n"])
            logger.debug(f"合并提取输出: {raw_output}")

            # 解析多字段输出
            results = {}
            for field in fields:
                value = self._parse_single_field(raw_output, field)
                results[field] = value
            return results

        except Exception as e:
            logger.error(f"合并提取失败: {e}")
            return {f: None for f in fields}

    def _keyword_context_extract(self, full_text: str, field: str) -> Optional[str]:
        """
        关键字定位+上下文扩展提取

        流程：
        1. 将全文按段落分割
        2. 用关键字列表搜索命中段落
        3. 向上下扩展指定段落数，组成focused context
        4. 用专用prompt送入LLM提取
        """
        config = FIELD_KEYWORDS.get(field)
        if not config:
            return None

        keywords = config["keywords"]
        expand_before = config["expand_before"]
        expand_after = config["expand_after"]
        prompt_template = config["prompt"]

        # 按段落分割（空行或换行分段）
        paragraphs = self._split_paragraphs(full_text)
        if not paragraphs:
            return None

        # 查找关键字命中的段落索引
        hit_indices = self._find_keyword_hits(paragraphs, keywords)

        if not hit_indices:
            logger.debug(f"字段 '{field}' 未找到关键字命中段落")
            return None

        # 扩展上下文
        context = self._expand_context(paragraphs, hit_indices, expand_before, expand_after)

        # 控制context长度（不超过1200字符，适配模型token限制）
        if len(context) > 1200:
            context = context[:1200]

        logger.debug(f"字段 '{field}' 定位到 {len(hit_indices)} 个命中段落，上下文 {len(context)} 字符")

        # 用专用prompt提取
        prompt = f"""{prompt_template}

Text:
{context}

JSON:"""

        try:
            raw_output = self._llm.raw_call(prompt, stop=["\n\n"])
            logger.debug(f"字段 '{field}' 模型输出: {raw_output}")

            # 解析输出
            value = self._parse_single_field(raw_output, field)
            return value

        except Exception as e:
            logger.error(f"关键字定位提取失败 ({field}): {e}")
            return None

    def _split_paragraphs(self, text: str) -> List[str]:
        """
        将文本按段落分割

        策略：按换行分割，合并过短的行
        """
        lines = text.split("\n")
        paragraphs = []
        buffer = ""

        for line in lines:
            line = line.strip()
            if not line:
                if buffer:
                    paragraphs.append(buffer)
                    buffer = ""
                continue

            # 如果当前行很短且buffer也短，合并
            if len(line) < 15 and buffer and len(buffer) < 50:
                buffer += " " + line
            else:
                if buffer:
                    paragraphs.append(buffer)
                buffer = line

        if buffer:
            paragraphs.append(buffer)

        return paragraphs

    def _find_keyword_hits(self, paragraphs: List[str], keywords: List[str]) -> List[int]:
        """
        查找包含关键字的段落索引

        Returns:
            命中段落的索引列表（去重排序）
        """
        hits = set()

        for i, para in enumerate(paragraphs):
            for kw in keywords:
                # 支持正则关键字（如 "自.*起.*至.*止"）
                try:
                    if re.search(kw, para):
                        hits.add(i)
                        break
                except re.error:
                    # 非正则关键字，直接包含匹配
                    if kw in para:
                        hits.add(i)
                        break

        return sorted(hits)

    def _expand_context(
        self,
        paragraphs: List[str],
        hit_indices: List[int],
        expand_before: int,
        expand_after: int,
    ) -> str:
        """
        围绕命中段落扩展上下文

        将所有命中段落及其上下文合并为一个连续文本块
        """
        # 计算需要包含的段落范围
        include_indices = set()
        for idx in hit_indices:
            start = max(0, idx - expand_before)
            end = min(len(paragraphs) - 1, idx + expand_after)
            for i in range(start, end + 1):
                include_indices.add(i)

        # 按顺序拼接
        sorted_indices = sorted(include_indices)
        context_parts = []
        prev_idx = -2

        for idx in sorted_indices:
            # 如果段落不连续，加分隔
            if idx > prev_idx + 1 and context_parts:
                context_parts.append("...")
            context_parts.append(paragraphs[idx])
            prev_idx = idx

        return "\n".join(context_parts)

    def _parse_single_field(self, raw_output: str, field: str) -> Optional[str]:
        """从模型输出中解析单个字段值"""
        import json

        # 尝试JSON解析
        try:
            # 清理
            text = raw_output.strip()
            # 提取{...}
            brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
            if brace_match:
                text = brace_match.group(0)
            text = re.sub(r",\s*}", "}", text)
            data = json.loads(text)
            if isinstance(data, dict):
                value = data.get(field)
                if value and str(value).strip():
                    return str(value).strip()
        except (json.JSONDecodeError, TypeError):
            pass

        # 正则回退：匹配 "field": "value"
        pattern = rf'"{field}"\s*:\s*"([^"]*)"'
        match = re.search(pattern, raw_output)
        if match:
            return match.group(1)

        # 如果输出很短且不像JSON，可能模型直接输出了值
        if len(raw_output) < 200 and "{" not in raw_output:
            cleaned = raw_output.strip().strip('"').strip("'")
            if cleaned and len(cleaned) > 3:
                return cleaned

        return None

    def _parse_payment_schedule(
        self, full_text: str, current_results: Dict[str, Any]
    ) -> Optional[List[Dict[str, Any]]]:
        """
        结构化解析付款条件

        优先用正则从原文解析，如果解析不出来则用 payment_terms 字段的值
        """
        # 获取合同总金额（用于计算百分比对应金额）
        total_amount = None
        amount_data = current_results.get("total_amount", {})
        if isinstance(amount_data, dict) and amount_data.get("value"):
            try:
                val = str(amount_data["value"]).replace(",", "")
                total_amount = float(re.search(r"[\d.]+", val).group())
            except (ValueError, AttributeError):
                pass

        # 定位付款相关段落
        paragraphs = self._split_paragraphs(full_text)
        payment_keywords = [
            "付款", "支付", "结算", "款项",
            "付款方式", "支付方式", "合同价款",
        ]
        hit_indices = self._find_keyword_hits(paragraphs, payment_keywords)

        if hit_indices:
            payment_text = self._expand_context(paragraphs, hit_indices, 1, 6)
        else:
            # 回退到 payment_terms 字段
            pt_data = current_results.get("payment_terms", {})
            payment_text = pt_data.get("value", "") if isinstance(pt_data, dict) else ""

        if not payment_text:
            return None

        # 调用结构化解析器
        schedule = self._payment_parser.parse(payment_text, total_amount)
        return schedule if schedule else None

    def _llm_extract_from_chunks(
        self, chunks: List[str], fields: List[str]
    ) -> Dict[str, Any]:
        """LLM分块提取并合并（用于普通字段）"""
        merged = {}

        for chunk in chunks:
            chunk_result = self._llm.extract(chunk, "contract", fields)
            for key, value in chunk_result.items():
                if value and (key not in merged or not merged[key]):
                    merged[key] = value

        return merged

    def _cross_validate(
        self,
        regex_results: Dict[str, Any],
        llm_results: Dict[str, Any],
        fields: List[str],
    ) -> Dict[str, Any]:
        """
        交叉校验正则和LLM结果

        规则：
        - 两者一致 → 高置信度采用
        - 两者不一致 → 按字段优先级决定
        - 只有一方命中 → 采用命中方，降低置信度
        - 都没命中 → null
        """
        final = {}

        for field in fields:
            regex_data = regex_results.get(field, {"values": [], "confidence": 0.0})
            regex_values = regex_data.get("values", []) if isinstance(regex_data, dict) else []
            regex_conf = regex_data.get("confidence", 0.0) if isinstance(regex_data, dict) else 0.0
            regex_best = regex_values[0] if regex_values else None

            llm_value = llm_results.get(field)

            priority = FIELD_PRIORITY.get(field, "llm")

            result = self._resolve_field(
                field=field,
                regex_value=regex_best,
                regex_confidence=regex_conf,
                llm_value=llm_value,
                priority=priority,
            )

            # 只保留请求的字段
            final[field] = result

        return final

    def _resolve_field(
        self,
        field: str,
        regex_value: Optional[str],
        regex_confidence: float,
        llm_value: Optional[str],
        priority: str,
    ) -> Dict[str, Any]:
        """
        解决单个字段的正则/LLM冲突

        Returns:
            {
                "value": 最终值,
                "confidence": 置信度,
                "source": 来源,
                "regex_value": 正则值,
                "llm_value": LLM值,
            }
        """
        has_regex = regex_value is not None and regex_value != ""
        has_llm = llm_value is not None and str(llm_value).strip() != ""

        llm_str = str(llm_value).strip() if has_llm else None

        # 情况1：两者都没有
        if not has_regex and not has_llm:
            return {
                "value": None,
                "confidence": 0.0,
                "source": "none",
                "regex_value": None,
                "llm_value": None,
            }

        # 情况2：只有正则
        if has_regex and not has_llm:
            conf = regex_confidence * 0.85  # 单方命中降低置信度
            return {
                "value": regex_value,
                "confidence": conf,
                "source": "regex_only",
                "regex_value": regex_value,
                "llm_value": None,
            }

        # 情况3：只有LLM
        if not has_regex and has_llm:
            # 用验证器检查LLM输出格式
            is_valid = self._validator.validate(field, llm_str)
            conf = 0.7 if is_valid else 0.5
            return {
                "value": llm_str,
                "confidence": conf,
                "source": "llm_only",
                "regex_value": None,
                "llm_value": llm_str,
            }

        # 情况4：两者都有 - 需要对比
        is_consistent = self._check_consistency(field, regex_value, llm_str)

        if is_consistent:
            # 一致：高置信度
            return {
                "value": regex_value,  # 一致时用正则值（格式更规范）
                "confidence": min(regex_confidence + 0.1, 0.98),
                "source": "cross_validated",
                "regex_value": regex_value,
                "llm_value": llm_str,
            }
        else:
            # 不一致：按优先级决定
            if priority == "regex":
                chosen = regex_value
                conf = regex_confidence * 0.8  # 不一致时降低置信度
                source = "regex_preferred"
            elif priority == "llm":
                chosen = llm_str
                conf = 0.65
                source = "llm_preferred"
            else:  # both - 选格式验证通过的
                regex_valid = self._validator.validate(field, regex_value)
                llm_valid = self._validator.validate(field, llm_str)
                if regex_valid and not llm_valid:
                    chosen = regex_value
                    conf = regex_confidence * 0.8
                    source = "regex_validated"
                elif llm_valid and not regex_valid:
                    chosen = llm_str
                    conf = 0.65
                    source = "llm_validated"
                else:
                    # 都通过或都不通过，选正则（格式更规范）
                    chosen = regex_value
                    conf = regex_confidence * 0.7
                    source = "regex_fallback"

            return {
                "value": chosen,
                "confidence": conf,
                "source": source,
                "regex_value": regex_value,
                "llm_value": llm_str,
            }

    def _check_consistency(self, field: str, regex_value: str, llm_value: str) -> bool:
        """
        检查正则和LLM结果是否一致

        不要求完全相同，允许格式差异：
        - 日期：2024年1月1日 == 2024-01-01
        - 金额：1,000.00元 == 1000
        - 名称：允许包含关系
        """
        if not regex_value or not llm_value:
            return False

        # 完全相同
        if regex_value.strip() == llm_value.strip():
            return True

        # 日期字段：规范化后比较
        if field in ("sign_date",):
            r_norm = self._normalize_for_compare(regex_value)
            l_norm = self._normalize_for_compare(llm_value)
            return r_norm == l_norm

        # 金额字段：提取数字比较
        if field in ("total_amount",):
            r_num = self._extract_number(regex_value)
            l_num = self._extract_number(llm_value)
            if r_num is not None and l_num is not None:
                return abs(r_num - l_num) < 0.01
            return False

        # 名称类字段：包含关系
        if field in ("party_a", "party_b", "contract_name"):
            r_clean = regex_value.replace(" ", "")
            l_clean = llm_value.replace(" ", "")
            return r_clean in l_clean or l_clean in r_clean

        # 其他字段：包含关系
        return regex_value in llm_value or llm_value in regex_value

    def _normalize_for_compare(self, value: str) -> str:
        """规范化字符串用于比较（去除空格、标点、统一分隔符）"""
        import re
        # 提取所有数字
        nums = re.findall(r"\d+", value)
        return "-".join(nums)

    def _extract_number(self, value: str) -> Optional[float]:
        """从字符串中提取数字"""
        import re
        # 去除逗号
        value = value.replace(",", "").replace("，", "")
        # 处理万元
        if "万" in value:
            m = re.search(r"([\d.]+)", value)
            if m:
                return float(m.group(1)) * 10000
        # 处理亿元
        if "亿" in value:
            m = re.search(r"([\d.]+)", value)
            if m:
                return float(m.group(1)) * 100000000
        # 普通数字
        m = re.search(r"([\d.]+)", value)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
        return None

    def get_simple_result(self, full_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        将详细结果简化为 field: value 格式

        Args:
            full_result: extract() 的完整输出

        Returns:
            {"contract_name": "xxx", "party_a": "xxx", ...}
        """
        return {
            field: data["value"]
            for field, data in full_result.items()
        }
