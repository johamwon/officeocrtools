"""
主合同识别模块

功能：
- 从多页文档中识别主合同的页码范围
- 过滤掉附件、保密协议、廉政承诺书等非主合同内容
- 只返回主合同文本供后续提取使用

识别策略：
- 主合同起始：文档第一页（封面）或正文第一页
- 主合同结束：遇到以下标志之一：
  1. "（以下无正文）"
  2. "附件[一二三四五六七八九十]"/"附件1"/"附件2"等
  3. 独立协议标题（"保密及信息安全协议"、"廉政承诺书"等）
"""
import re
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


# 主合同结束标志（按优先级排序）
MAIN_CONTRACT_END_MARKERS = [
    # 最强标志：显式声明正文结束
    {
        "pattern": r"[（(]\s*以下\s*无\s*正文\s*[)）]",
        "priority": 100,
        "name": "以下无正文",
    },
    # 次强标志：附件开始
    {
        "pattern": r"^\s*附\s*件\s*[一二三四五六七八九十]\s*[:：]",
        "priority": 90,
        "name": "附件（中文数字）",
    },
    {
        "pattern": r"^\s*附\s*件\s*\d+\s*[:：]",
        "priority": 90,
        "name": "附件（阿拉伯数字）",
    },
    {
        "pattern": r"^\s*附\s*件\s*[一二三四五六七八九十]\s*$",
        "priority": 90,
        "name": "附件标题",
    },
]

# 独立协议/附件标题（这些不属于主合同）
SUB_DOCUMENT_TITLES = [
    r"保密\s*(?:及\s*信息\s*安全\s*)?协议",
    r"信息\s*安全\s*责任\s*承诺书",
    r"廉政\s*承诺书",
    r"廉洁\s*承诺书",
    r"反\s*腐败\s*承诺书",
    r"售后\s*服务\s*承诺书",
    r"质量\s*保证\s*承诺书",
    r"保密\s*条款",
]


class MainContractDetector:
    """主合同识别器"""

    def __init__(self):
        # 编译正则以提高性能
        self._end_markers = [
            (re.compile(m["pattern"], re.MULTILINE), m["priority"], m["name"])
            for m in MAIN_CONTRACT_END_MARKERS
        ]
        self._sub_titles = [re.compile(p) for p in SUB_DOCUMENT_TITLES]

    def detect_by_pages(
        self, pages: List[str]
    ) -> Tuple[int, int, str, Dict[str, Any]]:
        """
        从分页文本中识别主合同范围

        Args:
            pages: 按页分割的文本列表

        Returns:
            (start_page, end_page, main_text, metadata)
            - start_page: 主合同起始页（从0开始）
            - end_page: 主合同结束页（inclusive）
            - main_text: 主合同合并文本
            - metadata: 识别元数据（命中的标志、原因等）
        """
        if not pages:
            return 0, -1, "", {"reason": "empty_input"}

        total_pages = len(pages)
        start_page = self._detect_start_page(pages)
        end_page, end_info = self._detect_end_page(pages, start_page)

        # 提取主合同文本
        main_pages = pages[start_page:end_page + 1]
        main_text = "\n\n".join(main_pages)

        metadata = {
            "total_pages": total_pages,
            "start_page": start_page,
            "end_page": end_page,
            "main_pages": end_page - start_page + 1,
            "excluded_pages": total_pages - (end_page - start_page + 1),
            "end_marker": end_info,
        }

        logger.info(
            f"主合同识别: 总页数={total_pages}, 主合同页={start_page}-{end_page} "
            f"({metadata['main_pages']}页), 排除={metadata['excluded_pages']}页"
        )

        return start_page, end_page, main_text, metadata

    def _detect_start_page(self, pages: List[str]) -> int:
        """
        识别主合同起始页

        通常就是第0页（文档开头）。
        只有完全空白的页才跳过（阈值设为5字符以下）。
        """
        for i, page in enumerate(pages):
            # 只跳过几乎空白的页（<5字符）
            if len(page.strip()) < 5:
                continue
            return i
        return 0

    def _detect_end_page(
        self, pages: List[str], start_page: int
    ) -> Tuple[int, Dict[str, Any]]:
        """
        识别主合同结束页

        Returns:
            (end_page, info)
        """
        total_pages = len(pages)

        for i in range(start_page, total_pages):
            page = pages[i]

            # 检查结束标志
            for pattern, priority, name in self._end_markers:
                match = pattern.search(page)
                if match:
                    # "以下无正文" 通常在主合同最后一页，该页仍属于主合同
                    if "以下无正文" in name:
                        return i, {
                            "marker": name,
                            "matched_text": match.group(0),
                            "at_page": i,
                            "include_current": True,
                        }
                    # 附件标志：当前页已是附件，主合同到上一页结束
                    else:
                        end = max(start_page, i - 1)
                        return end, {
                            "marker": name,
                            "matched_text": match.group(0),
                            "at_page": i,
                            "include_current": False,
                        }

            # 检查独立协议标题（可能出现在页首）
            page_head = page[:200]
            for sub_pattern in self._sub_titles:
                if sub_pattern.search(page_head):
                    end = max(start_page, i - 1)
                    return end, {
                        "marker": "独立协议",
                        "matched_text": sub_pattern.pattern,
                        "at_page": i,
                        "include_current": False,
                    }

        # 没找到结束标志，默认到最后一页
        # 但对于多页文档，通常前半部分是主合同，做一个保守估计
        if total_pages > 5:
            # 检查签章页位置（通常主合同会有签章）
            signature_end = self._find_signature_page(pages, start_page)
            if signature_end > start_page:
                return signature_end, {
                    "marker": "签章页",
                    "at_page": signature_end,
                    "include_current": True,
                }

        return total_pages - 1, {"marker": "未找到结束标志", "at_page": total_pages - 1}

    def _find_signature_page(self, pages: List[str], start_page: int) -> int:
        """
        查找主合同的签章页位置

        签章页特征：
        - 包含"甲方"和"乙方"+ 签字/盖章
        - 通常在主合同末尾，附件前面
        """
        signature_pattern = re.compile(
            r"(?:甲方.*?(?:签字|盖章|公章)|乙方.*?(?:签字|盖章|公章))",
            re.DOTALL,
        )

        last_signature_page = start_page
        for i in range(start_page, len(pages)):
            page = pages[i]
            if signature_pattern.search(page):
                last_signature_page = i

        return last_signature_page

    def detect_by_text(
        self, text: str, page_separator: str = "\n\n"
    ) -> Tuple[str, Dict[str, Any]]:
        """
        从完整文本中识别主合同

        Args:
            text: 完整OCR文本（可能包含页分隔符）
            page_separator: 页分隔符

        Returns:
            (main_text, metadata)
        """
        pages = text.split(page_separator)
        start, end, main_text, metadata = self.detect_by_pages(pages)
        return main_text, metadata

    def split_pages_from_ocr_results(
        self, ocr_results: List[Dict[str, Any]]
    ) -> List[str]:
        """
        从OCR结果列表按页拆分为文本

        Args:
            ocr_results: OCR引擎返回的结果列表（含page字段）

        Returns:
            按页分组的文本列表
        """
        if not ocr_results:
            return []

        pages_dict: Dict[int, List[str]] = {}
        for item in ocr_results:
            page_idx = item.get("page", 0)
            pages_dict.setdefault(page_idx, []).append(item["text"])

        # 按页码排序
        max_page = max(pages_dict.keys()) if pages_dict else 0
        pages = []
        for i in range(max_page + 1):
            page_text = "\n".join(pages_dict.get(i, []))
            pages.append(page_text)

        return pages
