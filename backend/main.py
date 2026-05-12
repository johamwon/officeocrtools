"""
FastAPI 主入口
"""
import logging
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import crud, schemas, tasks
from .config import (
    UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_UPLOAD_SIZE, CORS_ORIGINS, BASE_DIR,
)
from .database import get_db, init_db

from notifier.config import DINGTALK_WEBHOOK_URL, DINGTALK_SECRET, NOTIFY_ENABLED, NOTIFY_CHECK_HOUR, NOTIFY_CHECK_MINUTE
from notifier.time_extractor import ScheduleExtractor
from notifier.scheduler import NotificationScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ========== 应用初始化 ==========

app = FastAPI(
    title="文档解析服务",
    description="基于PaddleOCR + 本地LLM的文档信息提取和合同管理系统",
    version="0.2.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    logger.info("初始化数据库...")
    init_db()
    logger.info("数据库已就绪")

    # 预加载 DocParser（避免首次请求等待太久）
    logger.info("预加载 OCR 模型...")
    tasks.get_parser()
    logger.info("OCR 模型加载完成")

    # 启动推送调度器
    if NOTIFY_ENABLED and DINGTALK_WEBHOOK_URL:
        global _notification_scheduler
        _notification_scheduler = NotificationScheduler(
            webhook_url=DINGTALK_WEBHOOK_URL,
            secret=DINGTALK_SECRET or None,
            check_hour=NOTIFY_CHECK_HOUR,
            check_minute=NOTIFY_CHECK_MINUTE,
        )
        _notification_scheduler.start()
        logger.info("钉钉推送调度器已启动")
    else:
        logger.info("推送调度器未启用（设置 NOTIFY_ENABLED=true 和 DINGTALK_WEBHOOK_URL 启用）")


_notification_scheduler = None


@app.on_event("shutdown")
def on_shutdown():
    tasks.shutdown()
    if _notification_scheduler:
        _notification_scheduler.stop()


# ========== 根路径 ==========

# 挂载前端静态文件
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def root():
    """返回前端首页"""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>文档解析服务</h1><p>前端未部署，访问 <a href='/docs'>/docs</a> 查看API文档</p>"
    )


@app.get("/api")
def api_info():
    return {
        "service": "文档解析服务",
        "version": "0.2.0",
        "docs": "/docs",
    }


@app.get("/api/health")
def health_check():
    """健康检查端点"""
    return {"status": "ok"}


# ========== 上传和解析 ==========

@app.post("/api/upload", response_model=schemas.UploadResponse)
def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """上传文档并创建解析任务"""
    # 校验文件格式
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {suffix}，支持: {ALLOWED_EXTENSIONS}",
        )

    # 保存文件（使用UUID避免重名）
    unique_name = f"{uuid.uuid4().hex}{suffix}"
    file_path = UPLOAD_DIR / unique_name

    file_size = 0
    with open(file_path, "wb") as f:
        while chunk := file.file.read(1024 * 1024):
            file_size += len(chunk)
            if file_size > MAX_UPLOAD_SIZE:
                f.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大，最大允许 {MAX_UPLOAD_SIZE // 1024 // 1024}MB",
                )
            f.write(chunk)

    # 创建任务
    task = crud.create_task(
        db=db,
        file_name=file.filename,
        file_path=str(file_path),
        file_size=file_size,
        doc_type=doc_type,
    )

    # 提交到线程池
    tasks.submit_parse_task(task.id)

    return schemas.UploadResponse(
        task_id=task.id,
        file_name=file.filename,
        status=task.status,
    )


# ========== 任务管理 ==========

@app.get("/api/tasks", response_model=List[schemas.ParseTaskResponse])
def list_tasks(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """列出解析任务"""
    return crud.list_tasks(db, skip=skip, limit=limit, status=status, doc_type=doc_type)


@app.get("/api/tasks/{task_id}", response_model=schemas.ParseTaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db)):
    """查询任务状态"""
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/tasks/{task_id}/result", response_model=schemas.ParseTaskDetail)
def get_task_result(task_id: int, db: Session = Depends(get_db)):
    """获取任务详细结果（含OCR文本和提取字段）"""
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("completed", "reviewed"):
        raise HTTPException(
            status_code=400,
            detail=f"任务尚未完成，当前状态: {task.status}",
        )
    return task


@app.get("/api/tasks/{task_id}/file")
def download_task_file(task_id: int, db: Session = Depends(get_db)):
    """下载任务的原始文件（用于前端预览）"""
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    file_path = Path(task.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已丢失")
    return FileResponse(path=file_path, filename=task.file_name)


@app.delete("/api/tasks/{task_id}", response_model=schemas.StatusResponse)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """删除任务"""
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 删除文件
    file_path = Path(task.file_path)
    if file_path.exists():
        file_path.unlink(missing_ok=True)
    crud.delete_task(db, task_id)
    return schemas.StatusResponse(success=True, message="任务已删除")


# ========== 合同管理 ==========

@app.post("/api/contracts", response_model=schemas.ContractResponse)
def create_contract(
    contract: schemas.ContractCreate,
    db: Session = Depends(get_db),
):
    """复审后入库合同，并自动派生时间节点"""
    task = crud.get_task(db, contract.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="关联任务不存在")

    new_contract = crud.create_contract(db, contract)

    # 自动派生时间节点
    try:
        extractor = ScheduleExtractor()
        fields = contract.model_dump(exclude_unset=True)
        schedules = extractor.extract_schedules(new_contract.id, fields)

        for s in schedules:
            if s.get("event_date") is None:
                continue  # 跳过日期未确定的节点
            schedule_data = schemas.ScheduleCreate(
                contract_id=new_contract.id,
                event_type=s["event_type"],
                event_name=s["event_name"],
                event_date=s["event_date"],
                amount=s.get("amount"),
                description=s.get("description"),
                remind_days=s.get("remind_days", [15, 7, 3, 1]),
            )
            crud.create_schedule(db, schedule_data)

        logger.info(f"合同 {new_contract.id} 入库成功，派生 {len(schedules)} 个时间节点")
    except Exception as e:
        logger.warning(f"时间节点派生失败（不影响入库）: {e}")

    return new_contract


@app.get("/api/contracts", response_model=List[schemas.ContractResponse])
def list_contracts(
    skip: int = 0,
    limit: int = 50,
    keyword: Optional[str] = Query(None, description="搜索合同名/编号/甲乙方"),
    db: Session = Depends(get_db),
):
    """列出合同"""
    return crud.list_contracts(db, skip=skip, limit=limit, keyword=keyword)


@app.get("/api/contracts/{contract_id}", response_model=schemas.ContractResponse)
def get_contract(contract_id: int, db: Session = Depends(get_db)):
    """获取合同详情"""
    contract = crud.get_contract(db, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    return contract


@app.put("/api/contracts/{contract_id}", response_model=schemas.ContractResponse)
def update_contract(
    contract_id: int,
    update_data: schemas.ContractUpdate,
    db: Session = Depends(get_db),
):
    """更新合同"""
    contract = crud.update_contract(db, contract_id, update_data)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    return contract


@app.delete("/api/contracts/{contract_id}", response_model=schemas.StatusResponse)
def delete_contract(contract_id: int, db: Session = Depends(get_db)):
    """删除合同"""
    if not crud.delete_contract(db, contract_id):
        raise HTTPException(status_code=404, detail="合同不存在")
    return schemas.StatusResponse(success=True, message="合同已删除")


@app.get(
    "/api/contracts/{contract_id}/schedules",
    response_model=List[schemas.ScheduleResponse],
)
def list_contract_schedules(contract_id: int, db: Session = Depends(get_db)):
    """列出合同的时间节点"""
    contract = crud.get_contract(db, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    return crud.list_schedules_by_contract(db, contract_id)


# ========== 辅助接口 ==========

@app.get("/api/doc-types")
def list_doc_types():
    """列出支持的文档类型"""
    parser = tasks.get_parser()
    return {"doc_types": parser.list_doc_types()}


@app.post("/api/notify/check", response_model=schemas.StatusResponse)
def trigger_notification_check():
    """手动触发一次推送检查（调试用）"""
    if not _notification_scheduler:
        raise HTTPException(status_code=400, detail="推送调度器未启用")
    _notification_scheduler.run_check_now()
    return schemas.StatusResponse(success=True, message="推送检查已执行")


if __name__ == "__main__":
    import uvicorn
    from .config import API_HOST, API_PORT
    uvicorn.run(app, host=API_HOST, port=API_PORT)
