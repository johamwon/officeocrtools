"""
配置管理模块
"""
import os
from pathlib import Path

# OCR配置（PaddleOCR 3.x）
OCR_CONFIG = {
    # 关闭预处理模型（加速）
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": False,
    # 使用轻量模型（速度提升2-3倍，精度略降）
    "text_detection_model_name": "PP-OCRv5_mobile_det",
    "text_recognition_model_name": "PP-OCRv5_mobile_rec",
    # 降低检测分辨率（加速20-30%）
    "text_det_limit_side_len": 736,
}

# 如果设置了自定义模型目录，配置模型路径
_paddleocr_model_dir = os.getenv("PADDLEX_MODEL_DIR", "")
if _paddleocr_model_dir:
    _model_dir = Path(_paddleocr_model_dir)
    _det_dir = _model_dir / "PP-OCRv5_mobile_det"
    _rec_dir = _model_dir / "PP-OCRv5_mobile_rec"
    if _det_dir.exists():
        OCR_CONFIG["text_detection_model_dir"] = str(_det_dir)
    if _rec_dir.exists():
        OCR_CONFIG["text_recognition_model_dir"] = str(_rec_dir)

# 本地模型配置（OpenAI兼容API）
LLM_CONFIG = {
    "base_url": os.getenv("LLM_BASE_URL", "http://localhost:8080/v1"),
    "api_key": os.getenv("LLM_API_KEY", "not-needed"),
    "model": os.getenv("LLM_MODEL", ""),
    "temperature": 0.1,
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "800")),
    "context_size": int(os.getenv("LLM_CONTEXT_SIZE", "4096")),
}

# 文本处理配置（根据模型context动态调整）
_context_size = LLM_CONFIG["context_size"]
TEXT_CONFIG = {
    # 单次送入模型的最大字符数（按context的30%估算，留空间给prompt和输出）
    "max_chunk_chars": min(int(_context_size * 0.3), 2400),
    # 分块时的重叠字符数
    "chunk_overlap": 100,
}

# 支持的文件格式
SUPPORTED_FORMATS = [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".pdf"]
