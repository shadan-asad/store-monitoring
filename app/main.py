from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse
import uuid
from app.services.report_service import ReportService
from app.models.models import ReportStatus
from app.database import get_db
from sqlalchemy.orm import Session
from fastapi import Depends

app = FastAPI(title="Store Monitoring System")

@app.post("/trigger_report")
async def trigger_report(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Trigger a new report generation
    """
    report_id = str(uuid.uuid4())
    report_service = ReportService(db)
    
    # Create initial report record
    report_service.create_report(report_id)
    
    # Trigger background task
    background_tasks.add_task(report_service.generate_report, report_id)
    
    return {"report_id": report_id}

@app.get("/get_report/{report_id}")
async def get_report(report_id: str, db: Session = Depends(get_db)):
    """
    Get report status or download completed report
    """
    report_service = ReportService(db)
    report = report_service.get_report(report_id)
    
    if not report:
        return {"status": "Not Found"}
    
    if report.status == ReportStatus.RUNNING:
        return {"status": "Running"}
    
    if report.status == ReportStatus.COMPLETED:
        return FileResponse(
            report.file_path,
            media_type="text/csv",
            filename=f"report_{report_id}.csv"
        )
    
    return {"status": "Failed"} 