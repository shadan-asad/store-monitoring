from app.models.models import Report, ReportStatus, Store, BusinessHours, StoreStatus
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import pandas as pd
import pytz
import os
from typing import List, Dict, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ReportService:
    def __init__(self, db: Session):
        self.db = db
        self.reports_dir = "reports"
        os.makedirs(self.reports_dir, exist_ok=True)

    def create_report(self, report_id: str) -> Report:
        """Create a new report record"""
        report = Report(
            report_id=report_id,
            status=ReportStatus.RUNNING,
            created_at=datetime.utcnow()
        )
        self.db.add(report)
        self.db.commit()
        return report

    def get_report(self, report_id: str) -> Report:
        """Get report by ID"""
        return self.db.query(Report).filter(Report.report_id == report_id).first()

    def _get_store_timezone(self, store_id: str) -> str:
        """Get store timezone or return default"""
        store = self.db.query(Store).filter(Store.store_id == store_id).first()
        return store.timezone if store else "America/Chicago"

    def _get_business_hours(self, store_id: str) -> List[Dict]:
        """Get business hours for a store"""
        hours = self.db.query(BusinessHours).filter(BusinessHours.store_id == store_id).all()
        if not hours:
            # Default to 24/7 if no hours specified
            return [{"day": i, "start": "00:00", "end": "23:59"} for i in range(7)]
        return [{"day": h.day_of_week, "start": h.start_time_local, "end": h.end_time_local} for h in hours]

    def _is_within_business_hours(self, timestamp: datetime, store_id: str) -> bool:
        """Check if timestamp is within business hours"""
        timezone = pytz.timezone(self._get_store_timezone(store_id))
        local_time = timestamp.astimezone(timezone)
        day_of_week = local_time.weekday()
        time_str = local_time.strftime("%H:%M")
        
        business_hours = self._get_business_hours(store_id)
        for hours in business_hours:
            if hours["day"] == day_of_week:
                return hours["start"] <= time_str <= hours["end"]
        return False

    def _calculate_uptime_downtime(self, store_id: str, start_time: datetime, end_time: datetime) -> Tuple[float, float]:
        """Calculate uptime and downtime for a given time period"""
        status_updates = self.db.query(StoreStatus)\
            .filter(StoreStatus.store_id == store_id)\
            .filter(StoreStatus.timestamp_utc.between(start_time, end_time))\
            .order_by(StoreStatus.timestamp_utc)\
            .all()

        if not status_updates:
            return 0, 0

        total_minutes = (end_time - start_time).total_seconds() / 60
        uptime_minutes = 0
        downtime_minutes = 0

        for i in range(len(status_updates) - 1):
            current = status_updates[i]
            next_update = status_updates[i + 1]
            
            if not self._is_within_business_hours(current.timestamp_utc, store_id):
                continue

            time_diff = (next_update.timestamp_utc - current.timestamp_utc).total_seconds() / 60
            if current.status == "active":
                uptime_minutes += time_diff
            else:
                downtime_minutes += time_diff

        return uptime_minutes, downtime_minutes

    def generate_report(self, report_id: str):
        """Generate the report in background"""
        try:
            report = self.get_report(report_id)
            if not report:
                return

            # Get all stores
            stores = self.db.query(Store).all()
            current_time = datetime.utcnow()

            # Calculate time ranges
            last_hour = current_time - timedelta(hours=1)
            last_day = current_time - timedelta(days=1)
            last_week = current_time - timedelta(weeks=1)

            results = []
            for store in stores:
                # Calculate metrics for different time periods
                uptime_hour, downtime_hour = self._calculate_uptime_downtime(store.store_id, last_hour, current_time)
                uptime_day, downtime_day = self._calculate_uptime_downtime(store.store_id, last_day, current_time)
                uptime_week, downtime_week = self._calculate_uptime_downtime(store.store_id, last_week, current_time)

                results.append({
                    "store_id": store.store_id,
                    "uptime_last_hour": round(uptime_hour, 2),
                    "uptime_last_day": round(uptime_day / 60, 2),  # Convert to hours
                    "uptime_last_week": round(uptime_week / 60, 2),  # Convert to hours
                    "downtime_last_hour": round(downtime_hour, 2),
                    "downtime_last_day": round(downtime_day / 60, 2),  # Convert to hours
                    "downtime_last_week": round(downtime_week / 60, 2)  # Convert to hours
                })

            # Create DataFrame and save to CSV
            df = pd.DataFrame(results)
            file_path = os.path.join(self.reports_dir, f"report_{report_id}.csv")
            df.to_csv(file_path, index=False)

            # Update report status
            report.status = ReportStatus.COMPLETED
            report.file_path = file_path
            report.completed_at = datetime.utcnow()
            self.db.commit()

        except Exception as e:
            logger.error(f"Error generating report {report_id}: {str(e)}")
            report.status = ReportStatus.FAILED
            self.db.commit() 