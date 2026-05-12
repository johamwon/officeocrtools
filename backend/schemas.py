"""
Pydantic schemas（API请求/响应模型）
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


# ========== 通用 ==========

class StatusResponse(BaseModel):
    """通用状态响应"""
    success: bool
    message: str = ""


# ========== ParseTask ==========

class ParseTaskBase(BaseModel):
    file_name: str
    doc_type: str


class ParseTaskCreate(ParseTaskBase):
    pass


class ParseTaskResponse(ParseTaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    progress: int
    file_size: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ParseTaskDetail(ParseTaskResponse):
    """任务详情（含解析结果）"""
    ocr_text: Optional[str] = None
    main_text: Optional[str] = None
    raw_result: Optional[Dict[str, Any]] = None
    timing: Optional[Dict[str, Any]] = None


# ========== Contract ==========

class ContractBase(BaseModel):
    contract_name: Optional[str] = None
    contract_number: Optional[str] = None
    party_a: Optional[str] = None
    party_b: Optional[str] = None
    sign_date: Optional[date] = None
    total_amount: Optional[Decimal] = None
    service_content: Optional[str] = None
    performance_period: Optional[str] = None
    payment_terms: Optional[str] = None
    delivery_deadline: Optional[date] = None
    warranty_end_date: Optional[date] = None
    payment_schedules: Optional[List[Dict[str, Any]]] = None
    extra_fields: Optional[Dict[str, Any]] = None


class ContractCreate(ContractBase):
    """入库请求（从任务复审后入库）"""
    task_id: int
    reviewer: Optional[str] = None
    review_notes: Optional[str] = None


class ContractUpdate(ContractBase):
    """更新合同信息"""
    reviewer: Optional[str] = None
    review_notes: Optional[str] = None


class ContractResponse(ContractBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: Optional[int] = None
    reviewer: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ========== Schedule ==========

class ScheduleBase(BaseModel):
    event_type: str
    event_name: str
    event_date: date
    amount: Optional[Decimal] = None
    description: Optional[str] = None
    remind_days: Optional[List[int]] = Field(default_factory=lambda: [15, 7, 3, 1])


class ScheduleCreate(ScheduleBase):
    contract_id: int
    extra_data: Optional[Dict[str, Any]] = None


class ScheduleResponse(ScheduleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: int
    status: str
    last_notified_date: Optional[date] = None
    created_at: datetime


# ========== 上传响应 ==========

class UploadResponse(BaseModel):
    """上传文档后的响应"""
    task_id: int
    file_name: str
    status: str
    message: str = "文件已上传，解析任务已创建"


# ========== 复审相关 ==========

class ReviewSubmit(BaseModel):
    """提交复审修改"""
    fields: Dict[str, Any]
    reviewer: Optional[str] = None
    notes: Optional[str] = None
