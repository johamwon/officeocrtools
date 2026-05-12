"""
文本预处理模块 - OCR结果清洗、压缩、分块
"""
import re
from typing import List, Tuple

from .config import TEXT_CONFIG


class TextProcessor:
    """OCR文本预处理器，负责清洗和分块"""

    def __init__(self, max_chunk_chars: int = None, chunk_overlap: int = None):
        self.max_chunk_chars = max_chunk_chars or TEXT_CONFIG["max_chunk_chars"]
        self.chunk_overlap = chunk_overlap or TEXT_CONFIG["chunk_overlap"]

    def clean(self, text: str) -> str:
        """
        清洗OCR文本：
        - 去除多余空白
        - 修正常见OCR错误
        - 规范化标点
        """
        # 去除多余空白行
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 去除行首尾空白
        lines = [line.strip() for line in text.split("\n")]
        # 去除空行
        lines = [line for line in lines if line]
        # 合并过短的碎片行（OCR常见问题）
        merged = self._merge_fragments(lines)
        return "\n".join(merged)

    def _merge_fragments(self, lines: List[str], min_length: int = 2) -> List[str]:
        """合并过短的碎片文本到相邻行"""
        if not lines:
            return lines

        merged = []
        buffer = ""

        for line in lines:
            if len(line) < min_length:
                # 短片段用空格拼接到buffer
                if buffer:
                    buffer += " " + line
                else:
                    buffer = line
            else:
                if buffer:
                    merged.append(buffer)
                buffer = line

        if buffer:
            merged.append(buffer)

        return merged

    def compress(self, text: str) -> str:
        """
        压缩文本以节省token：
        - 去除重复的分隔线
        - 压缩连续空格
        - 去除无意义字符
        """
        # 去除重复分隔线（如 -----, =====, ****）
        text = re.sub(r"[-=*_]{3,}", "", text)
        # 压缩连续空格为单个
        text = re.sub(r"[ \t]+", " ", text)
        # 去除特殊无意义字符
        text = re.sub(r"[□■◆◇○●△▽※]", "", text)
        return text.strip()

    def chunk(self, text: str) -> List[str]:
        """
        将文本分块，确保每块不超过max_chunk_chars

        分块策略：优先按段落分，其次按行分
        """
        if len(text) <= self.max_chunk_chars:
            return [text]

        chunks = []
        lines = text.split("\n")
        current_chunk = ""

        for line in lines:
            # 如果单行就超长，强制截断
            if len(line) > self.max_chunk_chars:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                # 按字符数截断长行
                for i in range(0, len(line), self.max_chunk_chars - self.chunk_overlap):
                    chunks.append(line[i:i + self.max_chunk_chars])
                continue

            # 正常累积
            if len(current_chunk) + len(line) + 1 > self.max_chunk_chars:
                chunks.append(current_chunk)
                # 保留重叠部分
                overlap_start = max(0, len(current_chunk) - self.chunk_overlap)
                current_chunk = current_chunk[overlap_start:] + "\n" + line
            else:
                current_chunk = current_chunk + "\n" + line if current_chunk else line

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def process(self, text: str) -> Tuple[str, List[str]]:
        """
        完整预处理流程：清洗 → 压缩 → 分块

        Returns:
            (cleaned_text, chunks) - 清洗后的完整文本和分块列表
        """
        cleaned = self.clean(text)
        compressed = self.compress(cleaned)
        chunks = self.chunk(compressed)
        return compressed, chunks
