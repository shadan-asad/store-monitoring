from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class ReportStatus(enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True)
    store_id = Column(String, unique=True, index=True)
    timezone = Column(String, default="America/Chicago")
    
    business_hours = relationship("BusinessHours", back_populates="store")
    status_updates = relationship("StoreStatus", back_populates="store")

class BusinessHours(Base):
    __tablename__ = "business_hours"

    id = Column(Integer, primary_key=True)
    store_id = Column(String, ForeignKey("stores.store_id"))
    day_of_week = Column(Integer)  # 0=Monday, 6=Sunday
    start_time_local = Column(String)
    end_time_local = Column(String)
    
    store = relationship("Store", back_populates="business_hours")

class StoreStatus(Base):
    __tablename__ = "store_status"

    id = Column(Integer, primary_key=True)
    store_id = Column(String, ForeignKey("stores.store_id"))
    timestamp_utc = Column(DateTime)
    status = Column(String)  # active or inactive
    
    store = relationship("Store", back_populates="status_updates")

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    report_id = Column(String, unique=True, index=True)
    status = Column(Enum(ReportStatus))
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime)
    completed_at = Column(DateTime, nullable=True) 