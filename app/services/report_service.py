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
        # Configuration for batch processing
        # Set to -1 to process all batches, or set to a specific batch number (1-based) to process only that batch
        self.process_batch = -1  # Default to process all batches

    def set_process_batch(self, batch_number: int):
        """Set which batch to process. -1 for all batches, or specific batch number (1-based)"""
        self.process_batch = batch_number
        logger.info(f"Set to process batch: {batch_number if batch_number > 0 else 'ALL'}")

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
        logger.debug(f"Calculating uptime/downtime for store {store_id} from {start_time} to {end_time}")
        
        # Get all status updates for the store in the time range in a single query
        status_updates = self.db.query(StoreStatus)\
            .filter(StoreStatus.store_id == store_id)\
            .filter(StoreStatus.timestamp_utc.between(start_time, end_time))\
            .order_by(StoreStatus.timestamp_utc)\
            .all()

        if not status_updates:
            logger.debug(f"No status updates found for store {store_id} in the given time range")
            return 0, 0

        logger.debug(f"Found {len(status_updates)} status updates for store {store_id}")

        # Get business hours once for the store
        business_hours = self._get_business_hours(store_id)
        timezone = pytz.timezone(self._get_store_timezone(store_id))
        logger.debug(f"Store {store_id} timezone: {timezone}")

        uptime_minutes = 0
        downtime_minutes = 0
        total_processed = 0
        skipped_outside_hours = 0

        for i in range(len(status_updates) - 1):
            current = status_updates[i]
            next_update = status_updates[i + 1]
            
            # Convert to local time once
            local_time = current.timestamp_utc.astimezone(timezone)
            day_of_week = local_time.weekday()
            time_str = local_time.strftime("%H:%M")
            
            # Check business hours
            is_within_hours = False
            for hours in business_hours:
                if hours["day"] == day_of_week:
                    is_within_hours = hours["start"] <= time_str <= hours["end"]
                    break

            if not is_within_hours:
                skipped_outside_hours += 1
                continue

            time_diff = (next_update.timestamp_utc - current.timestamp_utc).total_seconds() / 60
            if current.status == "active":
                uptime_minutes += time_diff
            else:
                downtime_minutes += time_diff
            total_processed += 1

        logger.debug(f"Store {store_id} metrics: uptime={uptime_minutes:.2f}min, downtime={downtime_minutes:.2f}min, "
                    f"processed={total_processed}, skipped={skipped_outside_hours}")
        return uptime_minutes, downtime_minutes

    def generate_report(self, report_id: str):
        """Generate the report in background"""
        start_time = datetime.utcnow()
        logger.info(f"Starting report generation for report_id: {report_id} at {start_time}")
        
        try:
            report = self.get_report(report_id)
            if not report:
                logger.error(f"Report not found for report_id: {report_id}")
                return

            logger.info("Fetching all stores from db")
            stores = self.db.query(Store).all()
            logger.info(f"Found {len(stores)} stores to process")

            # Get the time range from the data
            oldest_status = self.db.query(StoreStatus).order_by(StoreStatus.timestamp_utc).first()
            newest_status = self.db.query(StoreStatus).order_by(StoreStatus.timestamp_utc.desc()).first()
            
            if not oldest_status or not newest_status:
                logger.error("No status data found in the db")
                report.status = ReportStatus.FAILED
                self.db.commit()
                return

            # Calculate time ranges based on the data
            end_time = newest_status.timestamp_utc
            last_hour = end_time - timedelta(hours=1)
            last_day = end_time - timedelta(days=1)
            last_week = end_time - timedelta(weeks=1)
            
            logger.info(f"Using data time range: {oldest_status.timestamp_utc} to {end_time}")

            # Process stores in batches
            batch_size = 100
            results = []
            total_batches = (len(stores) + batch_size - 1) // batch_size
            
            # Determine which batches to process
            if self.process_batch == -1:
                batches_to_process = range(0, len(stores), batch_size)
                logger.info("Processing ALL batches")
            else:
                if self.process_batch < 1 or self.process_batch > total_batches:
                    logger.error(f"Invalid batch number: {self.process_batch}. Must be between 1 and {total_batches}")
                    report.status = ReportStatus.FAILED
                    self.db.commit()
                    return
                start_idx = (self.process_batch - 1) * batch_size
                batches_to_process = [start_idx]
                logger.info(f"Processing only batch {self.process_batch} of {total_batches}")
            
            for i in batches_to_process:
                batch_start_time = datetime.utcnow()
                batch = stores[i:i+batch_size]
                current_batch = i // batch_size + 1
                logger.info(f"\n{'='*50}")
                logger.info(f"Processing batch {current_batch}/{total_batches} ({len(batch)} stores)")
                
                batch_results = []
                for store_index, store in enumerate(batch, 1):
                    store_start_time = datetime.utcnow()
                    logger.info(f"Processing store {i + store_index}/{len(stores)}: {store.store_id}")
                    
                    # Calculate metrics for different time periods
                    uptime_hour, downtime_hour = self._calculate_uptime_downtime(store.store_id, last_hour, end_time)
                    uptime_day, downtime_day = self._calculate_uptime_downtime(store.store_id, last_day, end_time)
                    uptime_week, downtime_week = self._calculate_uptime_downtime(store.store_id, last_week, end_time)

                    store_results = {
                        "store_id": store.store_id,
                        "uptime_last_hour": round(uptime_hour, 2),
                        "uptime_last_day": round(uptime_day / 60, 2),  # Convert to hours
                        "uptime_last_week": round(uptime_week / 60, 2),  # Convert to hours
                        "downtime_last_hour": round(downtime_hour, 2),
                        "downtime_last_day": round(downtime_day / 60, 2),  # Convert to hours
                        "downtime_last_week": round(downtime_week / 60, 2)  # Convert to hours
                    }
                    
                    store_end_time = datetime.utcnow()
                    store_duration = (store_end_time - store_start_time).total_seconds()
                    logger.info(f"Completed store {store.store_id} in {store_duration:.2f} seconds")
                    
                    batch_results.append(store_results)
                
                results.extend(batch_results)
                
                # Commit after each batch to prevent memory issues
                self.db.commit()
                
                batch_end_time = datetime.utcnow()
                batch_duration = (batch_end_time - batch_start_time).total_seconds()
                logger.info(f"Completed batch {current_batch}/{total_batches} in {batch_duration:.2f} seconds")
                
                # Calculate and log progress
                progress = (current_batch / total_batches) * 100
                elapsed_time = (batch_end_time - start_time).total_seconds()
                estimated_total_time = elapsed_time / (current_batch / total_batches)
                remaining_time = estimated_total_time - elapsed_time
                
                logger.info(f"Progress: {progress:.1f}% complete. "
                          f"Estimated time remaining: {remaining_time/60:.1f} minutes")
                logger.info(f"{'='*50}\n")

            logger.info("Creating DataFrame from results...")
            # Create DataFrame and save to CSV
            df = pd.DataFrame(results)
            file_path = os.path.join(self.reports_dir, f"report_{report_id}.csv")
            logger.info(f"Saving report to {file_path}")
            df.to_csv(file_path, index=False)

            # Update report status
            logger.info("Updating report status to completed...")
            report.status = ReportStatus.COMPLETED
            report.file_path = file_path
            report.completed_at = datetime.utcnow()
            self.db.commit()
            
            end_time = datetime.utcnow()
            total_duration = (end_time - start_time).total_seconds()
            logger.info(f"Report generation completed successfully for report_id: {report_id}")
            logger.info(f"Total processing time: {total_duration/60:.1f} minutes")
            logger.info(f"Average time per store: {total_duration/len(stores):.2f} seconds")
            logger.info(f"Average time per batch: {total_duration/total_batches:.2f} seconds")

        except Exception as e:
            logger.error(f"Error generating report {report_id}: {str(e)}", exc_info=True)
            report.status = ReportStatus.FAILED
            self.db.commit() 