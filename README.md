# 文档OCR及关键信息解析工具

基于 PaddleOCR + 本地小模型（Qwen2.5-Coder-1.5B）的文档信息提取工具。

## 特性

- PaddleOCR 文字识别，支持图片和PDF
- 本地小模型关键信息提取，无需联网
- 针对 4096 token 限制优化：文本压缩、分块处理、分批提取
- 内置多种文档类型模板（发票、身份证、营业执照、收据、合同）
- 支持自定义文档类型和提取指令

## 安装

```bash
pip install -r requirements.txt
```

## 启动本地模型

使用 llama.cpp 启动模型服务：

```bash
# 启动 llama.cpp server（默认端口8080）
./llama-server -m qwen2.5-coder-1.5b-instruct-q8_0.gguf -c 4096 --port 8080
```

或使用 Ollama：

```bash
ollama run qwen2.5-coder:1.5b
# 默认API地址为 http://localhost:11434/v1
```

## 使用方式

### 命令行

```bash
# 解析发票
python -m doc_parser invoice.jpg --type invoice

# 快速模式（只提取关键字段）
python -m doc_parser invoice.jpg --type invoice --quick

# 指定提取字段
python -m doc_parser invoice.jpg --type invoice --fields invoice_number,total_with_tax

# 仅OCR
python -m doc_parser document.png --ocr-only

# 自定义提取
python -m doc_parser doc.jpg --custom "Extract all dates, output JSON list"

# 列出支持的文档类型
python -m doc_parser --list-types

# 指定模型地址
python -m doc_parser invoice.jpg --type invoice --llm-url http://localhost:11434/v1
```

### Python API

```python
from doc_parser import DocParser

# 初始化
parser = DocParser()

# 解析发票
result = parser.parse("invoice.jpg", doc_type="invoice")
print(result["fields"])
# {'invoice_number': '12345678', 'date': '2024-01-15', 'total_with_tax': '1180.00', ...}

# 快速模式
result = parser.parse("invoice.jpg", doc_type="invoice", quick_mode=True)

# 仅OCR
text = parser.ocr_only("document.png")

# 自定义提取
answer = parser.custom_extract("doc.jpg", "Extract all person names as JSON list")
```

## 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | `http://localhost:8080/v1` | 模型API地址 |
| `LLM_API_KEY` | `not-needed` | API密钥 |
| `LLM_MODEL` | `qwen2.5-coder-1.5b-instruct` | 模型名称 |

## 支持的文档类型

| 类型 | 说明 | 关键字段 |
|------|------|----------|
| `invoice` | 增值税发票 | 发票号码、日期、价税合计 |
| `id_card` | 身份证 | 姓名、身份证号、出生日期 |
| `business_license` | 营业执照 | 企业名称、信用代码、法人 |
| `receipt` | 收据/小票 | 商户、日期、金额 |
| `contract` | 合同 | 合同名称、甲方、乙方、金额 |

## 自定义文档类型

创建 JSON 文件放入自定义 schema 目录：

```json
{
  "name": "报价单",
  "description": "报价单信息提取",
  "fields": {
    "supplier": "供应商",
    "quote_date": "报价日期",
    "total_amount": "总金额",
    "valid_until": "有效期至"
  },
  "key_fields": ["supplier", "total_amount"]
}
```

```python
parser = DocParser(custom_schema_dir="./my_schemas")
result = parser.parse("quote.jpg", doc_type="quote")
```

## 架构说明

```
doc_parser/
├── __init__.py          # 包入口
├── __main__.py          # python -m 入口
├── config.py            # 配置管理
├── ocr_engine.py        # PaddleOCR封装
├── text_processor.py    # 文本清洗/压缩/分块
├── llm_extractor.py     # 本地模型调用
├── schema_manager.py    # 文档类型模板管理
├── pipeline.py          # 主流程串联
└── main.py              # CLI入口
```

### 处理流程

```
文档输入 → PaddleOCR识别 → 文本清洗压缩 → 分块(如需要) → 模型提取 → 后处理 → 结构化输出
```

### 针对小模型的优化

1. **文本压缩**：去除OCR噪声、无意义符号、重复分隔线
2. **分块策略**：长文档按段落分块，每块≤1200字符
3. **分批提取**：每次最多提取4个字段，降低模型负担
4. **极简Prompt**：不用角色设定，直接任务+格式
5. **多级解析**：JSON解析 → 代码块提取 → 正则兜底
