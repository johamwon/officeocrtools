"""
异步解析任务

使用线程池执行OCR+LLM解析任务，避免阻塞API请求。
DocParser实例全局单例（避免每次重新加载PaddleOCR模型）
注意：PaddleOCR不是线程安全的，使用锁保护调用。
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from doc_parser import DocParser

from . import crud
from .config import MAX_WORKERS
from .database import SessionLocal

logger = logging.getLogger(__name__)

# 全局DocParser单例（懒加载）
_parser: Optional[DocParser] = None
_parser_lock = threading.Lock()  # 保护 DocParser 初始化和调用

# 线程池（WAL模式下SQLite支持并发写入，可以多worker）
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="parser")


def get_parser() -> DocParser:
    """懒加载 DocParser 单例（首次调用会加载OCR和LLM）"""
    global _parser
    if _parser is None:
        with _parser_lock:
            if _parser is None:  # double-check
                logger.info("初始化 DocParser（加载OCR模型）...")
                _parser = DocParser()
                logger.info("DocParser 初始化完成")
    return _parser


def parse_task(task_id: int):
    """
    执行解析任务（在线程池中运行）
    使用锁保护 PaddleOCR 调用（非线程安全）

    Args:
        task_id: 任务ID
    """
    db = SessionLocal()
    try:
        task = crud.get_task(db, task_id)
        if not task:
            logger.error(f"任务不存在: {task_id}")
            return

        logger.info(f"开始解析任务 {task_id}: {task.file_name}")
        crud.update_task_status(db, task_id, "processing", progress=10)

        # 执行解析（加锁保护PaddleOCR）
        parser = get_parser()
        with _parser_lock:
            result = parser.parse(
                file_path=task.file_path,
                doc_type=task.doc_type,
            )

        # 保存结果
        crud.update_task_result(
            db,
            task_id=task_id,
            ocr_text=result.get("ocr_text", ""),
            main_text=result.get("main_text"),
            raw_result=result,
            timing=result.get("metadata", {}).get("timing", {}),
        )
        logger.info(f"任务 {task_id} 解析完成")

    except Exception as e:
        logger.exception(f"任务 {task_id} 解析失败")
        crud.update_task_status(
            db, task_id, "failed", error_message=str(e)
        )
    finally:
        db.close()


def submit_parse_task(task_id: int):
    """提交解析任务到线程池（非阻塞）"""
    logger.info(f"提交任务 {task_id} 到线程池")
    _executor.submit(parse_task, task_id)


def shutdown():
    """关闭线程池（优雅退出用）"""
    _executor.shutdown(wait=True)
