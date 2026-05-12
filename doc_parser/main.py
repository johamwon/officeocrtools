"""
命令行入口
"""
import argparse
import json
import logging
import sys

from .pipeline import DocParser


def main():
    parser = argparse.ArgumentParser(
        description="文档OCR及关键信息解析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 解析发票
  python -m doc_parser invoice.jpg --type invoice

  # 只提取关键字段（快速模式）
  python -m doc_parser invoice.jpg --type invoice --quick

  # 指定提取字段
  python -m doc_parser invoice.jpg --type invoice --fields invoice_number,total_with_tax

  # 仅OCR不提取
  python -m doc_parser document.png --ocr-only

  # 自定义提取指令
  python -m doc_parser doc.jpg --custom "Extract all person names, output as JSON list"

  # 列出支持的文档类型
  python -m doc_parser --list-types
        """,
    )

    parser.add_argument("file", nargs="?", help="文档文件路径")
    parser.add_argument("--type", "-t", dest="doc_type", help="文档类型")
    parser.add_argument("--fields", "-f", help="指定提取字段（逗号分隔）")
    parser.add_argument("--quick", "-q", action="store_true", help="快速模式，只提取关键字段")
    parser.add_argument("--ocr-only", action="store_true", help="仅执行OCR")
    parser.add_argument("--custom", help="自定义提取指令")
    parser.add_argument("--list-types", action="store_true", help="列出支持的文档类型")
    parser.add_argument("--output", "-o", help="输出文件路径（JSON）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--llm-url", help="LLM API地址")
    parser.add_argument("--llm-model", help="LLM模型名称")

    args = parser.parse_args()

    # 配置日志
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 列出文档类型
    if args.list_types:
        doc_parser = DocParser()
        types = doc_parser.list_doc_types()
        print("支持的文档类型:")
        for t in types:
            print(f"  - {t}")
        return

    # 检查必要参数
    if not args.file:
        parser.error("请指定文档文件路径")

    # 构建LLM参数
    llm_kwargs = {}
    if args.llm_url:
        llm_kwargs["base_url"] = args.llm_url
    if args.llm_model:
        llm_kwargs["model"] = args.llm_model

    # 初始化解析器
    doc_parser = DocParser(llm_kwargs=llm_kwargs if llm_kwargs else None)

    # 仅OCR模式
    if args.ocr_only:
        text = doc_parser.ocr_only(args.file)
        print(text)
        return

    # 自定义提取
    if args.custom:
        result = doc_parser.custom_extract(args.file, args.custom)
        print(result)
        return

    # 标准解析模式
    if not args.doc_type:
        parser.error("请指定文档类型 (--type)")

    fields = args.fields.split(",") if args.fields else None

    result = doc_parser.parse(
        file_path=args.file,
        doc_type=args.doc_type,
        fields=fields,
        quick_mode=args.quick,
    )

    # 输出结果
    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"结果已保存到: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
