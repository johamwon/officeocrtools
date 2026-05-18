"""
LLM提取模块 - 调用本地小模型进行关键信息提取
针对 Qwen2.5-Coder-1.5B 优化
"""
import json
import re
import logging
from typing import Dict, Any, List, Optional

from openai import OpenAI

from .config import LLM_CONFIG
from .schema_manager import SchemaManager

logger = logging.getLogger(__name__)


class LLMExtractor:
    """
    本地小模型信息提取器

    针对 Qwen2.5-Coder-1.5B (4096 context) 的优化策略：
    1. 极简prompt，不用角色设定
    2. 强制JSON输出
    3. 分批提取字段（每次最多4个字段）
    4. 正则后处理兜底
    """

    # 每次提取的最大字段数（减轻模型负担）
    MAX_FIELDS_PER_CALL = 4

    def __init__(self, schema_manager: SchemaManager = None, **kwargs):
        config = {**LLM_CONFIG, **kwargs}
        self._client = OpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"],
        )
        self._model = config["model"]
        self._temperature = config["temperature"]
        self._max_tokens = config["max_tokens"]
        self._schema_manager = schema_manager or SchemaManager()

    def extract(
        self,
        text: str,
        doc_type: str,
        fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        从文本中提取指定字段

        Args:
            text: OCR识别后的文本
            doc_type: 文档类型
            fields: 要提取的字段列表，None则提取全部

        Returns:
            提取结果字典
        """
        all_fields = fields or list(self._schema_manager.get_fields(doc_type).keys())

        if not all_fields:
            logger.warning(f"未找到文档类型 '{doc_type}' 的字段定义")
            return {}

        # 如果字段数量少，一次性提取
        if len(all_fields) <= self.MAX_FIELDS_PER_CALL:
            return self._extract_batch(text, doc_type, all_fields)

        # 字段多时分批提取
        result = {}
        for i in range(0, len(all_fields), self.MAX_FIELDS_PER_CALL):
            batch_fields = all_fields[i:i + self.MAX_FIELDS_PER_CALL]
            batch_result = self._extract_batch(text, doc_type, batch_fields)
            result.update(batch_result)

        return result

    def extract_key_fields(self, text: str, doc_type: str) -> Dict[str, Any]:
        """只提取关键字段（快速模式）"""
        key_fields = self._schema_manager.get_key_fields(doc_type)
        return self._extract_batch(text, doc_type, key_fields)

    def _extract_batch(
        self, text: str, doc_type: str, fields: List[str]
    ) -> Dict[str, Any]:
        """单批次提取"""
        prompt = self._build_prompt(text, doc_type, fields)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stop=["\n\n"],
            )
            raw_output = response.choices[0].message.content.strip()
            logger.debug(f"模型原始输出: {raw_output}")
            return self._parse_output(raw_output, fields)

        except Exception as e:
            logger.error(f"模型调用失败: {e}")
            return {field: None for field in fields}

    def _build_prompt(self, text: str, doc_type: str, fields: List[str]) -> str:
        """
        构建提取prompt

        针对不同模型能力设计两种风格：
        - 代码模型（qwen-coder等）：极简指令
        - 通用模型（MiniCPM-V等）：给出JSON模板让模型填空
        """
        field_desc = self._schema_manager.build_field_prompt(doc_type, fields)

        # 根据配置的context_size动态计算最大文本长度
        from .config import LLM_CONFIG
        context_size = LLM_CONFIG.get("context_size", 4096)
        max_text_len = min(int(context_size * 0.3), 2400)

        if len(text) > max_text_len:
            text = text[:max_text_len]

        # 构建JSON模板（让模型填空，提高格式遵循率）
        json_template = "{\n"
        for i, field in enumerate(fields):
            json_template += f'  "{field}": "..."'
            if i < len(fields) - 1:
                json_template += ","
            json_template += "\n"
        json_template += "}"

        prompt = f"""请从以下文本中提取信息，严格按照JSON格式输出，不要输出其他内容。
需要提取的字段: {field_desc}

文本内容:
{text}

请按以下格式输出（将...替换为提取到的值，如果找不到则填null）:
{json_template}"""
        return prompt

    def _parse_output(self, raw: str, fields: List[str]) -> Dict[str, Any]:
        """
        解析模型输出，带多级容错处理

        尝试顺序：
        1. 直接JSON解析
        2. 提取JSON代码块
        3. 提取第一个{...}
        4. 宽松JSON提取（处理中文引号等）
        5. 正则匹配key-value（中英文冒号）
        """
        if not raw or not raw.strip():
            return {field: None for field in fields}

        # 尝试1：直接解析
        result = self._try_parse_json(raw)
        if result:
            return {k: v for k, v in result.items() if k in fields}

        # 尝试2：提取```json```代码块
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if json_match:
            result = self._try_parse_json(json_match.group(1))
            if result:
                return {k: v for k, v in result.items() if k in fields}

        # 尝试3：提取第一个{...}（支持嵌套）
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            json_str = raw[brace_start:brace_end + 1]
            result = self._try_parse_json(json_str)
            if result:
                return {k: v for k, v in result.items() if k in fields}

        # 尝试4：修复常见的非标准JSON（中文引号、缺少引号等）
        fixed = raw
        fixed = fixed.replace("\u201c", '"').replace("\u201d", '"')  # 中文双引号
        fixed = fixed.replace("\u2018", "'").replace("\u2019", "'")  # 中文单引号
        fixed = fixed.replace("：", ":").replace("，", ",")  # 中文标点
        brace_start = fixed.find("{")
        brace_end = fixed.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            result = self._try_parse_json(fixed[brace_start:brace_end + 1])
            if result:
                return {k: v for k, v in result.items() if k in fields}

        # 尝试5：正则逐字段匹配（支持中英文格式）
        logger.warning(f"JSON解析失败，尝试正则匹配。模型原始输出: {raw[:200]}")
        return self._regex_fallback(raw, fields)

    def _try_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """尝试解析JSON"""
        try:
            # 清理可能的尾部逗号
            text = re.sub(r",\s*}", "}", text)
            text = re.sub(r",\s*]", "]", text)
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    def _regex_fallback(self, text: str, fields: List[str]) -> Dict[str, Any]:
        """正则兜底提取（支持多种格式）"""
        result = {}
        for field in fields:
            value = None

            # 模式1: "field": "value"
            pattern = rf'"{field}"\s*:\s*"([^"]*)"'
            match = re.search(pattern, text)
            if match:
                value = match.group(1)

            # 模式2: "field": value（无引号值）
            if not value:
                pattern = rf'"{field}"\s*:\s*([^\s,}}"]+)'
                match = re.search(pattern, text)
                if match:
                    val = match.group(1).strip().strip('"').strip("'")
                    if val and val.lower() != "null":
                        value = val

            # 模式3: field: "value"（无引号key）
            if not value:
                pattern = rf'{field}\s*[:：]\s*["\']([^"\']+)["\']'
                match = re.search(pattern, text)
                if match:
                    value = match.group(1)

            # 模式4: field: value（完全无引号，中文冒号）
            if not value:
                pattern = rf'{field}\s*[:：]\s*(.+?)(?:\n|,|}}|$)'
                match = re.search(pattern, text)
                if match:
                    val = match.group(1).strip().strip('"').strip("'").strip(",")
                    if val and val.lower() not in ("null", "none", "...", ""):
                        value = val

            # 模式5: 数字值
            if not value:
                pattern = rf'"{field}"\s*:\s*([\d.]+)'
                match = re.search(pattern, text)
                if match:
                    value = match.group(1)

            result[field] = value

        return result

    def raw_extract(self, text: str, instruction: str) -> str:
        """
        自由提取模式 - 用自定义指令提取信息

        Args:
            text: 输入文本
            instruction: 提取指令

        Returns:
            模型原始输出
        """
        prompt = f"""{instruction}

Text:
{text}

Answer:"""

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"模型调用失败: {e}")
            return ""

    def raw_call(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        """
        直接调用模型（供其他模块复用client）

        Args:
            prompt: 完整的prompt文本
            max_tokens: 可选，覆盖默认max_tokens
            temperature: 可选，覆盖默认temperature
            stop: 可选，停止符

        Returns:
            模型输出文本
        """
        try:
            kwargs = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature if temperature is not None else self._temperature,
                "max_tokens": max_tokens if max_tokens is not None else self._max_tokens,
            }
            if stop:
                kwargs["stop"] = stop

            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"模型调用失败: {e}")
            return ""
