"""
OCR引擎模块 - 封装PaddleOCR 3.x

性能优化：
- 支持 max_pages 限制最大OCR页数
- 支持 early_stop 模式：逐页检测附件标志，遇到即停止
"""
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from paddleocr import PaddleOCR
from .config import OCR_CONFIG, SUPPORTED_FORMATS

# 附件/非主合同标志（用于提前终止OCR）
_STOP_PATTERNS = [
    re.compile(r"附\s*件\s*[一二三四五六七八九十\d]\s*[:：]?"),
    re.compile(r"保密\s*(?:及\s*信息\s*安全\s*)?协议"),
    re.compile(r"廉政\s*承诺书"),
    re.compile(r"[（(]\s*以下\s*无\s*正文\s*[)）]"),
]


class OCREngine:
    """PaddleOCR 3.x 封装，支持图片和PDF输入"""

    def __init__(self, **kwargs):
        config = {**OCR_CONFIG, **kwargs}
        self._ocr = PaddleOCR(**config)

    def recognize(
        self,
        file_path: str,
        max_pages: Optional[int] = None,
        early_stop: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        识别文档，返回结构化OCR结果（按页顺序）

        Args:
            file_path: 图片或PDF文件路径
            max_pages: 最大OCR页数（None=不限制）
            early_stop: 是否在检测到附件标志时提前停止

        Returns:
            列表，每个元素包含:
            - text, confidence, box, center_x, center_y, page
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix not in SUPPORTED_FORMATS:
            raise ValueError(f"不支持的文件格式: {suffix}，支持: {SUPPORTED_FORMATS}")

        all_parsed = []
        page_idx = 0
        found_end = False  # "以下无正文"标志

        for result in self._ocr.predict(str(file_path)):
            # 检查页数限制
            if max_pages and page_idx >= max_pages:
                break

            res_data = result.json.get("res", {})
            rec_texts = res_data.get("rec_texts", [])
            rec_scores = res_data.get("rec_scores", [])
            dt_polys = res_data.get("dt_polys", [])

            # 当前页的文本项
            page_items = []
            page_text_parts = []

            for i, text in enumerate(rec_texts):
                box = dt_polys[i] if i < len(dt_polys) else [[0, 0], [0, 0], [0, 0], [0, 0]]
                confidence = rec_scores[i] if i < len(rec_scores) else 0.0

                center_y = sum(p[1] for p in box) / 4
                center_x = sum(p[0] for p in box) / 4

                page_items.append({
                    "text": text,
                    "confidence": confidence,
                    "box": box,
                    "center_x": center_x,
                    "center_y": center_y,
                    "page": page_idx,
                })
                page_text_parts.append(text)

            # 页内按阅读顺序排序
            page_items.sort(key=lambda item: (round(item["center_y"] / 20) * 20, item["center_x"]))
            all_parsed.extend(page_items)

            # 提前终止检测
            if early_stop and page_idx > 0:
                page_text = " ".join(page_text_parts)

                # 检查是否遇到"以下无正文"（当前页仍保留，下一页停止）
                if re.search(r"[（(]\s*以下\s*无\s*正文\s*[)）]", page_text):
                    found_end = True
                    page_idx += 1
                    break

                # 如果上一页已经有"以下无正文"，当前页是签章页后的附件
                if found_end:
                    break

                # 检查是否遇到附件标志（当前页不保留）
                if page_idx >= 2:  # 至少保留前2页
                    for pat in _STOP_PATTERNS:
                        if pat.search(page_text[:200]):  # 只检查页首
                            # 移除当前页的结果
                            all_parsed = [item for item in all_parsed if item["page"] < page_idx]
                            found_end = True
                            break
                    if found_end:
                        break

            page_idx += 1

        return all_parsed

    def recognize_to_text(self, file_path: str, **kwargs) -> str:
        """识别文档并返回纯文本（按页顺序，页间用换行分隔）"""
        results = self.recognize(file_path, **kwargs)
        if not results:
            return ""

        lines = []
        current_page = 0

        for item in results:
            if item["page"] != current_page:
                lines.append("")
                current_page = item["page"]
            lines.append(item["text"])

        return "\n".join(lines)

    def recognize_to_blocks(self, file_path: str, line_threshold: float = 20.0, **kwargs) -> List[str]:
        """
        识别文档并按行分组返回文本块
        """
        results = self.recognize(file_path, **kwargs)
        if not results:
            return []

        lines = []
        current_line = []
        current_y = results[0]["center_y"]
        current_page = results[0]["page"]

        for item in results:
            if item["page"] != current_page:
                if current_line:
                    line_text = " ".join(r["text"] for r in current_line)
                    lines.append(line_text)
                    current_line = []
                lines.append("")
                current_page = item["page"]
                current_y = item["center_y"]

            if abs(item["center_y"] - current_y) > line_threshold:
                if current_line:
                    line_text = " ".join(r["text"] for r in current_line)
                    lines.append(line_text)
                current_line = [item]
                current_y = item["center_y"]
            else:
                current_line.append(item)

        if current_line:
            line_text = " ".join(r["text"] for r in current_line)
            lines.append(line_text)

        return lines
