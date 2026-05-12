"""
配置管理模块
"""
import os

# OCR配置（PaddleOCR 3.x）
OCR_CONFIG = {
    "lang": "ch",
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

# 本地模型配置（OpenAI兼容API）
LLM_CONFIG = {
    "base_url": os.getenv("LLM_BASE_URL", "http://localhost:8080/v1"),
    "api_key": os.getenv("LLM_API_KEY", "not-needed"),
    "model": os.getenv("LLM_MODEL", "qwen2.5-coder-1.5b-instruct"),
    "temperature": 0.1,
    "max_tokens": 400,
}

# 文本处理配置
TEXT_CONFIG = {
    # 单次送入模型的最大字符数（约1200中文字 ≈ 1500 tokens）
    "max_chunk_chars": 1200,
    # 分块时的重叠字符数
    "chunk_overlap": 100,
}

# 支持的文件格式
SUPPORTED_FORMATS = [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".pdf"]
