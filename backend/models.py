"""
数据库模型
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Numeric,
    JSON, ForeignKey, Boolean
)
from sqlalchemy.orm import relationship

from .database import Base


class ParseTask(Base):
    """解析任务表"""
    __tablename__ = "parse_tasks"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    doc_type = Column(String(50), nullable=False, index=True)

    # 状态：pending/processing/completed/failed/reviewed
    status = Column(String(20), default="pending", index=True)
    progress = Column(Integer, default=0)  # 0-100
    error_message = Column(Text)

    # 解析结果
    ocr_text = Column(Text)
    main_text = Column(Text)  # 主合同文本
    raw_result = Column(JSON)  # 完整的解析结果JSON

    # 时间统计
    timing = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # 关联的合同记录（如果已入库）
    contracts = relationship("Contract", back_populates="task")


class Contract(Base):
    """合同入库表"""
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("parse_tasks.id"), index=True)

    # 基本字段
    contract_name = Column(String(500))
    contract_number = Column(String(100), index=True)
    party_a = Column(String(255))
    party_b = Column(String(255))
    sign_date = Column(Date, index=True)
    total_amount = Column(Numeric(15, 2))

    # 详细字段
    service_content = Column(Text)
    performance_period = Column(Text)
    payment_terms = Column(Text)

    # 派生字段（用于webhook推送）
    delivery_deadline = Column(Date, index=True)      # 交付截止日
    warranty_end_date = Column(Date)                  # 质保到期日
    payment_schedules = Column(JSON)                  # 付款计划

    # 复审信息
    reviewer = Column(String(100))
    reviewed_at = Column(DateTime)
    review_notes = Column(Text)

    # 元数据
    extra_fields = Column(JSON)  # 其他未分类字段
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    task = relationship("ParseTask", back_populates="contracts")
    schedules = relationship("Schedule", back_populates="contract", cascade="all, delete-orphan")


class Schedule(Base):
    """时间节点表（用于webhook推送）"""
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), index=True)

    # 节点类型：payment/delivery/warranty/deposit_return/custom
    event_type = Column(String(50), nullable=False, index=True)
    event_name = Column(String(200), nullable=False)
    event_date = Column(Date, nullable=False, index=True)

    amount = Column(Numeric(15, 2))  # 相关金额（如付款金额）
    description = Column(Text)

    # 提醒配置
    remind_days = Column(JSON, default=[15, 7, 3, 1])  # 提前提醒天数列表
    last_notified_date = Column(Date)                  # 上次推送日期

    # 状态：pending/notified/completed/cancelled
    status = Column(String(20), default="pending", index=True)

    extra_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract = relationship("Contract", back_populates="schedules")


class Notification(Base):
    """推送日志表"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), index=True)

    channel = Column(String(20), default="dingtalk")  # dingtalk/wechat/email
    webhook_url = Column(String(500))
    message = Column(Text)
    status = Column(String(20))  # success/failed
    response = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow, index=True)
