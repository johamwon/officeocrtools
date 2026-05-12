"""
数据库CRUD操作
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from . import models, schemas


# ========== ParseTask ==========

def create_task(
    db: Session, file_name: str, file_path: str, file_size: int, doc_type: str
) -> models.ParseTask:
    task = models.ParseTask(
        file_name=file_name,
        file_path=file_path,
        file_size=file_size,
        doc_type=doc_type,
        status="pending",
        progress=0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> Optional[models.ParseTask]:
    return db.query(models.ParseTask).filter(models.ParseTask.id == task_id).first()


def list_tasks(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> List[models.ParseTask]:
    q = db.query(models.ParseTask)
    if status:
        q = q.filter(models.ParseTask.status == status)
    if doc_type:
        q = q.filter(models.ParseTask.doc_type == doc_type)
    return q.order_by(models.ParseTask.created_at.desc()).offset(skip).limit(limit).all()


def update_task_status(
    db: Session,
    task_id: int,
    status: str,
    progress: Optional[int] = None,
    error_message: Optional[str] = None,
) -> Optional[models.ParseTask]:
    task = get_task(db, task_id)
    if not task:
        return None
    task.status = status
    if progress is not None:
        task.progress = progress
    if error_message is not None:
        task.error_message = error_message
    if status == "processing" and not task.started_at:
        task.started_at = datetime.utcnow()
    if status in ("completed", "failed"):
        task.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def update_task_result(
    db: Session,
    task_id: int,
    ocr_text: str,
    main_text: Optional[str],
    raw_result: Dict[str, Any],
    timing: Dict[str, Any],
) -> Optional[models.ParseTask]:
    task = get_task(db, task_id)
    if not task:
        return None
    task.ocr_text = ocr_text
    task.main_text = main_text
    task.raw_result = raw_result
    task.timing = timing
    task.status = "completed"
    task.progress = 100
    task.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task_id: int) -> bool:
    task = get_task(db, task_id)
    if not task:
        return False
    db.delete(task)
    db.commit()
    return True


# ========== Contract ==========

def create_contract(
    db: Session, contract_data: schemas.ContractCreate
) -> models.Contract:
    data = contract_data.model_dump(exclude_unset=True)
    contract = models.Contract(**data)
    contract.reviewed_at = datetime.utcnow()
    db.add(contract)
    db.commit()
    db.refresh(contract)

    # 更新关联任务状态为 reviewed
    if contract.task_id:
        update_task_status(db, contract.task_id, "reviewed")

    return contract


def get_contract(db: Session, contract_id: int) -> Optional[models.Contract]:
    return db.query(models.Contract).filter(models.Contract.id == contract_id).first()


def list_contracts(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    keyword: Optional[str] = None,
) -> List[models.Contract]:
    q = db.query(models.Contract)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (models.Contract.contract_name.like(like))
            | (models.Contract.contract_number.like(like))
            | (models.Contract.party_a.like(like))
            | (models.Contract.party_b.like(like))
        )
    return q.order_by(models.Contract.created_at.desc()).offset(skip).limit(limit).all()


def update_contract(
    db: Session, contract_id: int, update_data: schemas.ContractUpdate
) -> Optional[models.Contract]:
    contract = get_contract(db, contract_id)
    if not contract:
        return None
    data = update_data.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(contract, key, value)
    db.commit()
    db.refresh(contract)
    return contract


def delete_contract(db: Session, contract_id: int) -> bool:
    contract = get_contract(db, contract_id)
    if not contract:
        return False
    db.delete(contract)
    db.commit()
    return True


# ========== Schedule ==========

def create_schedule(
    db: Session, schedule_data: schemas.ScheduleCreate
) -> models.Schedule:
    data = schedule_data.model_dump(exclude_unset=True)
    schedule = models.Schedule(**data)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def list_schedules_by_contract(
    db: Session, contract_id: int
) -> List[models.Schedule]:
    return (
        db.query(models.Schedule)
        .filter(models.Schedule.contract_id == contract_id)
        .order_by(models.Schedule.event_date)
        .all()
    )


def list_pending_schedules(db: Session) -> List[models.Schedule]:
    """获取所有待推送的节点"""
    return (
        db.query(models.Schedule)
        .filter(models.Schedule.status == "pending")
        .order_by(models.Schedule.event_date)
        .all()
    )
