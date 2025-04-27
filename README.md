# Store Monitoring System

A backend system for monitoring store uptime and downtime during business hours.

## Features

- Store status monitoring
- Business hours tracking
- Timezone-aware calculations
- Report generation with uptime/downtime metrics
- Background task processing for reports

## Prerequisites

- Python 3.8+
- PostgreSQL
- pip

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up the database:
```bash
# Create a PostgreSQL database named 'store_monitoring'
# Update the DATABASE_URL in .env file if needed
```

4. Create a .env file:
```
DATABASE_URL=postgresql://postgres:postgres@localhost/store_monitoring
```

5. Initialize the database and load data:
```bash
# Create database tables
python -c "from app.database import Base, engine; Base.metadata.create_all(bind=engine)"

# Load initial data
python app/scripts/load_data.py
```

## Running the Application

1. Start the FastAPI server:
```bash
uvicorn app.main:app --reload
```

2. The API will be available at http://localhost:8000

## API Endpoints

1. Trigger Report Generation:
```
POST /trigger_report
Response: {"report_id": "uuid"}
```

2. Get Report Status/Download:
```
GET /get_report/{report_id}
Response: 
- If running: {"status": "Running"}
- If complete: CSV file download
- If failed: {"status": "Failed"}
```

## Project Structure

```
store-monitoring/
├── app/
│   ├── main.py              # FastAPI application
│   ├── database.py          # Database configuration
│   ├── models/
│   │   └── models.py        # Database models
│   ├── services/
│   │   └── report_service.py # Business logic
│   └── scripts/
│       └── load_data.py     # Data loading script
├── reports/                 # Generated reports directory
├── requirements.txt         # Project dependencies
└── README.md               # This file
```

## Data Sources

The system uses three CSV files:
1. `store_status.csv`: Store activity status
2. `menu_hours.csv`: Business hours
3. `timezones.csv`: Store timezones

## Notes

- The system assumes missing business hours as 24/7 operation
- Default timezone is America/Chicago if not specified
- Reports are generated asynchronously in the background
- All timestamps are stored in UTC 