"""
Schema管理模块 - 定义各类文档的提取字段模板
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional, List


# 内置文档类型schema
BUILTIN_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "invoice": {
        "name": "发票",
        "description": "增值税发票信息提取",
        "fields": {
            "invoice_code": "发票代码",
            "invoice_number": "发票号码",
            "date": "开票日期",
            "total_amount": "合计金额",
            "tax_amount": "税额",
            "total_with_tax": "价税合计",
            "seller_name": "销售方名称",
            "buyer_name": "购买方名称",
        },
        "key_fields": ["invoice_number", "date", "total_with_tax"],
    },
    "id_card": {
        "name": "身份证",
        "description": "身份证信息提取",
        "fields": {
            "name": "姓名",
            "gender": "性别",
            "ethnicity": "民族",
            "birth_date": "出生日期",
            "address": "住址",
            "id_number": "身份证号码",
        },
        "key_fields": ["name", "id_number", "birth_date"],
    },
    "business_license": {
        "name": "营业执照",
        "description": "营业执照信息提取",
        "fields": {
            "company_name": "企业名称",
            "credit_code": "统一社会信用代码",
            "legal_person": "法定代表人",
            "registered_capital": "注册资本",
            "establishment_date": "成立日期",
            "business_scope": "经营范围",
            "address": "住所",
        },
        "key_fields": ["company_name", "credit_code", "legal_person"],
    },
    "receipt": {
        "name": "收据",
        "description": "收据/小票信息提取",
        "fields": {
            "merchant_name": "商户名称",
            "date": "日期",
            "total_amount": "总金额",
            "payment_method": "支付方式",
        },
        "key_fields": ["merchant_name", "date", "total_amount"],
    },
    "contract": {
        "name": "合同",
        "description": "合同关键信息提取",
        "fields": {
            "contract_name": "合同名称",
            "contract_number": "合同编号",
            "party_a": "甲方",
            "party_b": "乙方",
            "sign_date": "签订日期",
            "total_amount": "合同金额",
            "service_content": "服务内容/标的物",
            "performance_period": "履行期限(起止日期)",
            "payment_terms": "付款方式和条件",
        },
        "key_fields": ["contract_name", "party_a", "party_b", "total_amount", "service_content", "performance_period", "payment_terms"],
    },
}


class SchemaManager:
    """文档schema管理器"""

    def __init__(self, custom_schema_dir: Optional[str] = None):
        self._schemas = dict(BUILTIN_SCHEMAS)
        if custom_schema_dir:
            self._load_custom_schemas(custom_schema_dir)

    def _load_custom_schemas(self, schema_dir: str):
        """从目录加载自定义schema（JSON文件）"""
        schema_path = Path(schema_dir)
        if not schema_path.exists():
            return

        for json_file in schema_path.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    schema = json.load(f)
                name = json_file.stem
                self._schemas[name] = schema
            except (json.JSONDecodeError, KeyError):
                continue

    def get_schema(self, doc_type: str) -> Optional[Dict[str, Any]]:
        """获取指定文档类型的schema"""
        return self._schemas.get(doc_type)

    def list_types(self) -> List[str]:
        """列出所有支持的文档类型"""
        return list(self._schemas.keys())

    def get_fields(self, doc_type: str) -> Dict[str, str]:
        """获取指定文档类型的字段定义"""
        schema = self.get_schema(doc_type)
        if not schema:
            return {}
        return schema.get("fields", {})

    def get_key_fields(self, doc_type: str) -> List[str]:
        """获取关键字段列表（用于分步提取时优先提取）"""
        schema = self.get_schema(doc_type)
        if not schema:
            return []
        return schema.get("key_fields", list(schema.get("fields", {}).keys()))

    def build_field_prompt(self, doc_type: str, fields: Optional[List[str]] = None) -> str:
        """
        构建字段提示文本，用于prompt

        Args:
            doc_type: 文档类型
            fields: 指定提取的字段列表，None则提取全部

        Returns:
            字段描述字符串，如 "invoice_number(发票号码), date(开票日期)"
        """
        all_fields = self.get_fields(doc_type)
        if not all_fields:
            return ""

        if fields:
            selected = {k: v for k, v in all_fields.items() if k in fields}
        else:
            selected = all_fields

        parts = [f"{k}({v})" for k, v in selected.items()]
        return ", ".join(parts)
