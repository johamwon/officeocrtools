"""
主流程模块 - 串联OCR和信息提取
"""
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from .ocr_engine import OCREngine
from .text_processor import TextProcessor
from .llm_extractor import LLMExtractor
from .schema_manager import SchemaManager
from .contract_extractor import ContractExtractor
from .main_contract_detector import MainContractDetector
from .ocr_cache import OCRCache

logger = logging.getLogger(__name__)


class DocParser:
    """
    文档解析器主入口

    使用方式:
        parser = DocParser()
        result = parser.parse("invoice.jpg", doc_type="invoice")
        print(result)
    """

    def __init__(
        self,
        custom_schema_dir: Optional[str] = None,
        ocr_kwargs: Optional[Dict] = None,
        llm_kwargs: Optional[Dict] = None,
    ):
        """
        初始化文档解析器

        Args:
            custom_schema_dir: 自定义schema目录路径
            ocr_kwargs: OCR引擎额外参数
            llm_kwargs: LLM提取器额外参数
        """
        self._schema_manager = SchemaManager(custom_schema_dir)
        self._ocr = OCREngine(**(ocr_kwargs or {}))
        self._text_processor = TextProcessor()
        self._extractor = LLMExtractor(
            schema_manager=self._schema_manager,
            **(llm_kwargs or {}),
        )
        # 合同专用混合提取器
        self._contract_extractor = ContractExtractor(
            llm_extractor=self._extractor,
            schema_manager=self._schema_manager,
        )
        # 主合同识别器
        self._main_detector = MainContractDetector()
        # OCR缓存
        self._ocr_cache = OCRCache()

    def parse(
        self,
        file_path: str,
        doc_type: str,
        fields: Optional[List[str]] = None,
        quick_mode: bool = False,
        detect_main_contract: bool = True,
    ) -> Dict[str, Any]:
        """
        解析文档并提取关键信息

        Args:
            file_path: 文档文件路径
            doc_type: 文档类型（invoice/id_card/business_license/receipt/contract）
            fields: 指定提取字段，None则提取该类型全部字段
            quick_mode: 快速模式，只提取关键字段
            detect_main_contract: 合同类型是否启用主合同识别（过滤附件/协议）

        Returns:
            {
                "doc_type": "contract",
                "file": "contract.pdf",
                "ocr_text": "完整OCR文本",
                "main_text": "主合同文本（仅合同类型）",
                "fields": {...},
                "fields_detail": {...},  # 仅合同类型
                "metadata": {
                    "timing": {...},
                    "main_contract": {...}  # 仅合同类型
                }
            }
        """
        file_path = Path(file_path)
        logger.info(f"开始解析文档: {file_path}, 类型: {doc_type}")

        timing = {}
        total_start = time.perf_counter()

        # 1. OCR识别（带缓存）
        t0 = time.perf_counter()
        logger.info("执行OCR识别...")
        # 检查缓存
        ocr_results = self._ocr_cache.get(str(file_path))
        if ocr_results is not None:
            timing["ocr"] = round(time.perf_counter() - t0, 2)
            logger.info(f"OCR缓存命中: {timing['ocr']}s")
        else:
            # 合同类型启用提前终止（遇到附件/保密协议停止OCR）
            ocr_kwargs = {}
            if doc_type == "contract" and detect_main_contract:
                ocr_kwargs["early_stop"] = True
            ocr_results = self._ocr.recognize(str(file_path), **ocr_kwargs)
            # 写入缓存
            self._ocr_cache.put(str(file_path), ocr_results)
            timing["ocr"] = round(time.perf_counter() - t0, 2)
            logger.info(f"OCR完成: {timing['ocr']}s, 识别{len(ocr_results)}个文本框")

        ocr_text = self._ocr_results_to_text(ocr_results)

        if not ocr_text.strip():
            logger.warning("OCR未识别到文本")
            return self._build_empty_result(file_path, doc_type, timing, "OCR未识别到文本")

        # 2. 主合同识别（仅对合同类型）
        main_text = ocr_text
        main_metadata = None
        if doc_type == "contract" and detect_main_contract:
            t0 = time.perf_counter()
            pages = self._main_detector.split_pages_from_ocr_results(ocr_results)
            if len(pages) > 1:
                _, _, main_text, main_metadata = self._main_detector.detect_by_pages(pages)
                timing["main_detect"] = round(time.perf_counter() - t0, 2)
                logger.info(
                    f"主合同识别: {timing['main_detect']}s, "
                    f"保留{main_metadata['main_pages']}/{main_metadata['total_pages']}页"
                )

        # 3. 文本预处理
        t0 = time.perf_counter()
        cleaned_text, chunks = self._text_processor.process(main_text)
        timing["preprocess"] = round(time.perf_counter() - t0, 2)
        logger.info(f"文本预处理: {timing['preprocess']}s, {len(cleaned_text)}字符, {len(chunks)}块")

        # 4. 字段提取
        t0 = time.perf_counter()
        if doc_type == "contract":
            extracted, fields_detail = self._extract_contract(cleaned_text, fields)
        else:
            extracted = self._extract_generic(chunks, doc_type, fields, quick_mode)
            extracted = self._post_process(extracted, doc_type)
            fields_detail = None
        timing["extract"] = round(time.perf_counter() - t0, 2)
        logger.info(f"字段提取: {timing['extract']}s, 提取到{len(extracted)}个字段")

        timing["total"] = round(time.perf_counter() - total_start, 2)

        # 5. 构建统一输出结构
        result = {
            "doc_type": doc_type,
            "file": str(file_path),
            "ocr_text": ocr_text,
            "fields": extracted,
            "metadata": {
                "timing": timing,
                "chunks_used": len(chunks),
                "ocr_text_length": len(ocr_text),
            },
        }

        # 合同类型追加 main_text、fields_detail、main_metadata
        if doc_type == "contract":
            result["main_text"] = cleaned_text  # 主合同的清洗文本
            if fields_detail is not None:
                result["fields_detail"] = fields_detail
            if main_metadata:
                result["metadata"]["main_contract"] = main_metadata

        return result

    def _ocr_results_to_text(self, ocr_results: List[Dict[str, Any]]) -> str:
        """将OCR结果列表转为带页分隔的文本"""
        if not ocr_results:
            return ""

        lines = []
        current_page = 0
        for item in ocr_results:
            if item.get("page", 0) != current_page:
                lines.append("")
                current_page = item["page"]
            lines.append(item["text"])
        return "\n".join(lines)

    def _build_empty_result(
        self, file_path: Path, doc_type: str, timing: dict, error: str
    ) -> Dict[str, Any]:
        """构建空结果（OCR失败等场景）"""
        return {
            "doc_type": doc_type,
            "file": str(file_path),
            "ocr_text": "",
            "fields": {},
            "metadata": {"timing": timing, "error": error},
        }

    def _extract_contract(
        self, text: str, fields: Optional[List[str]]
    ) -> tuple:
        """合同类型专用提取（返回简洁结果和详细结果）"""
        logger.info("使用合同混合提取器（正则+LLM交叉校验）...")
        detailed = self._contract_extractor.extract(text, fields)
        simple = self._contract_extractor.get_simple_result(detailed)
        return simple, detailed

    def _extract_generic(
        self,
        chunks: List[str],
        doc_type: str,
        fields: Optional[List[str]],
        quick_mode: bool,
    ) -> Dict[str, Any]:
        """通用类型提取（纯LLM）"""
        if len(chunks) == 1:
            if quick_mode:
                return self._extractor.extract_key_fields(chunks[0], doc_type)
            return self._extractor.extract(chunks[0], doc_type, fields)
        return self._extract_from_chunks(chunks, doc_type, fields, quick_mode)

    def _extract_from_chunks(
        self,
        chunks: List[str],
        doc_type: str,
        fields: Optional[List[str]],
        quick_mode: bool,
    ) -> Dict[str, Any]:
        """从多个文本块中提取并合并"""
        merged = {}
        for i, chunk in enumerate(chunks):
            logger.debug(f"处理第 {i+1}/{len(chunks)} 块")
            if quick_mode:
                chunk_result = self._extractor.extract_key_fields(chunk, doc_type)
            else:
                chunk_result = self._extractor.extract(chunk, doc_type, fields)
            for key, value in chunk_result.items():
                if value and (key not in merged or not merged[key]):
                    merged[key] = value
        return merged

    def _post_process(self, extracted: Dict[str, Any], doc_type: str) -> Dict[str, Any]:
        """后处理：清理和规范化"""
        processed = {}
        for key, value in extracted.items():
            if value is None:
                processed[key] = None
                continue
            value = str(value).strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            if value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            if not value or value.lower() in ("null", "none", "n/a", "未知"):
                processed[key] = None
                continue
            processed[key] = value
        return processed

    # ========== 工具方法 ==========

    def ocr_only(self, file_path: str) -> str:
        """仅执行OCR，返回识别文本"""
        results = self._ocr.recognize(file_path)
        return self._ocr_results_to_text(results)

    def ocr_lines(self, file_path: str) -> List[str]:
        """执行OCR，返回按行分组的文本"""
        return self._ocr.recognize_to_blocks(file_path)

    def list_doc_types(self) -> List[str]:
        """列出支持的文档类型"""
        return self._schema_manager.list_types()

    def custom_extract(self, file_path: str, instruction: str) -> str:
        """
        自定义提取模式

        Args:
            file_path: 文档路径
            instruction: 自定义提取指令

        Returns:
            模型输出文本
        """
        ocr_text = self.ocr_only(file_path)
        cleaned, chunks = self._text_processor.process(ocr_text)
        text_to_use = chunks[0] if chunks else cleaned
        return self._extractor.raw_extract(text_to_use, instruction)

    def detect_main_contract_only(self, file_path: str) -> Dict[str, Any]:
        """
        只做主合同识别（不做字段提取），用于调试和预览

        Returns:
            {"main_text": "...", "metadata": {...}}
        """
        ocr_results = self._ocr.recognize(file_path)
        pages = self._main_detector.split_pages_from_ocr_results(ocr_results)
        start, end, main_text, metadata = self._main_detector.detect_by_pages(pages)
        return {
            "main_text": main_text,
            "metadata": metadata,
            "start_page": start,
            "end_page": end,
        }
