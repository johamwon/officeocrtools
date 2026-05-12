"""
定时任务调度器

每日检查所有待推送的时间节点，满足提醒条件时发送钉钉通知。
"""
import logging
from datetime import date, datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend import models, crud
from .dingtalk import DingTalkClient, build_schedule_message

logger = logging.getLogger(__name__)


class NotificationScheduler:
    """合同时间节点推送调度器"""

    def __init__(
        self,
        webhook_url: str,
        secret: Optional[str] = None,
        check_hour: int = 9,
        check_minute: int = 0,
    ):
        """
        Args:
            webhook_url: 钉钉 Webhook 地址
            secret: 加签密钥
            check_hour: 每日检查时间（小时）
            check_minute: 每日检查时间（分钟）
        """
        self._dingtalk = DingTalkClient(webhook_url, secret)
        self._scheduler = BackgroundScheduler()
        self._check_hour = check_hour
        self._check_minute = check_minute

    def start(self):
        """启动调度器"""
        self._scheduler.add_job(
            self._daily_check,
            "cron",
            hour=self._check_hour,
            minute=self._check_minute,
            id="daily_notification_check",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            f"推送调度器已启动，每日 {self._check_hour:02d}:{self._check_minute:02d} 检查"
        )

    def stop(self):
        """停止调度器"""
        self._scheduler.shutdown(wait=False)
        logger.info("推送调度器已停止")

    def run_check_now(self):
        """立即执行一次检查（手动触发/调试用）"""
        self._daily_check()

    def _daily_check(self):
        """每日检查逻辑"""
        logger.info("开始每日时间节点检查...")
        db = SessionLocal()
        try:
            pending_schedules = crud.list_pending_schedules(db)
            today = date.today()
            sent_count = 0

            for schedule in pending_schedules:
                if not schedule.event_date:
                    continue

                days_remaining = (schedule.event_date - today).days

                # 检查是否需要推送
                if self._should_notify(schedule, today, days_remaining):
                    success = self._send_notification(db, schedule, days_remaining)
                    if success:
                        sent_count += 1
                        # 更新上次推送日期
                        schedule.last_notified_date = today
                        # 如果已逾期超过30天，标记为完成（避免无限推送）
                        if days_remaining < -30:
                            schedule.status = "completed"
                        db.commit()

            logger.info(f"每日检查完成，推送了 {sent_count} 条通知")

        except Exception as e:
            logger.exception(f"每日检查异常: {e}")
        finally:
            db.close()

    def _should_notify(
        self, schedule: models.Schedule, today: date, days_remaining: int
    ) -> bool:
        """
        判断是否需要推送

        规则：
        - days_remaining 在 remind_days 列表中
        - 或者已逾期（每日推送直到处理）
        - 且今天还没推送过
        """
        # 今天已经推送过了
        if schedule.last_notified_date == today:
            return False

        remind_days = schedule.remind_days or [15, 7, 3, 1]

        # 在提醒天数列表中
        if days_remaining in remind_days:
            return True

        # 已逾期：每日推送
        if days_remaining <= 0:
            return True

        return False

    def _send_notification(
        self, db: Session, schedule: models.Schedule, days_remaining: int
    ) -> bool:
        """发送单条通知"""
        # 获取合同信息
        contract = crud.get_contract(db, schedule.contract_id)
        if not contract:
            logger.warning(f"节点 {schedule.id} 关联的合同不存在")
            return False

        # 构建消息
        message = build_schedule_message(
            contract_name=contract.contract_name or f"合同#{contract.id}",
            event_name=schedule.event_name,
            event_date=str(schedule.event_date),
            days_remaining=days_remaining,
            amount=float(schedule.amount) if schedule.amount else None,
            party_a=contract.party_a,
            party_b=contract.party_b,
            description=schedule.description,
        )

        # 发送
        result = self._dingtalk.send_markdown(
            title=f"合同提醒：{schedule.event_name}",
            content=message,
        )

        # 记录推送日志
        notification = models.Notification(
            schedule_id=schedule.id,
            channel="dingtalk",
            webhook_url=self._dingtalk._webhook_url[:50] + "...",
            message=message,
            status="success" if result["success"] else "failed",
            response=str(result.get("response", ""))[:500],
        )
        db.add(notification)
        db.commit()

        return result["success"]
