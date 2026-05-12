"""
OCR结果缓存模块

按文件内容hash缓存OCR结果，避免重复解析同一文件。
缓存存储在 storage/ocr_cache/ 目录下。
"""
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 默认缓存目录
_CACHE_DIR = Path(__file__).resolve().parent.parent / "storage" / "ocr_cache"


class OCRCache:
    """OCR结果缓存"""

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = Path(cache_dir) if cache_dir else _CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, file_path: str) -> Optional[List[Dict[str, Any]]]:
        """
        获取缓存的OCR结果

        Args:
            file_path: 原始文件路径

        Returns:
            缓存的OCR结果列表，未命中返回None
        """
        cache_file = self._get_cache_path(file_path)
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"OCR缓存命中: {file_path}")
            return data
        except (json.JSONDecodeError, IOError):
            return None

    def put(self, file_path: str, results: List[Dict[str, Any]]):
        """
        保存OCR结果到缓存

        Args:
            file_path: 原始文件路径
            results: OCR结果列表
        """
        cache_file = self._get_cache_path(file_path)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False)
            logger.debug(f"OCR结果已缓存: {cache_file.name}")
        except IOError as e:
            logger.warning(f"OCR缓存写入失败: {e}")

    def invalidate(self, file_path: str):
        """删除指定文件的缓存"""
        cache_file = self._get_cache_path(file_path)
        if cache_file.exists():
            cache_file.unlink()

    def clear(self):
        """清空所有缓存"""
        for f in self._cache_dir.glob("*.json"):
            f.unlink()
        logger.info("OCR缓存已清空")

    def _get_cache_path(self, file_path: str) -> Path:
        """根据文件内容hash生成缓存路径"""
        file_hash = self._compute_hash(file_path)
        return self._cache_dir / f"{file_hash}.json"

    def _compute_hash(self, file_path: str) -> str:
        """计算文件内容的MD5 hash"""
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
