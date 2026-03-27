import os
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from contextlib import asynccontextmanager

# --- 1. SECURE DATABASE SETUP ---
# The password is NO LONGER in this file. 
# Render/Koyeb will inject this securely via Environment Variables.
DATABASE_URL = os.getenv("DATABASE_URL")

# Only create the engine if the URL exists (prevents crashes during local testing)
if DATABASE_URL:
    # Ensure SQLAlchemy uses the psycopg2 driver
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://") and "psycopg2" not in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
        
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    engine = None

# --- 2. LIFESPAN (Startup Check) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n--- NEPSE Diary Cloud API Starting Up ---")
    if engine:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("✅ SUCCESS: Connected to Neon PostgreSQL (Read-Only Mode)!")
        except Exception as e:
            print(f"❌ ERROR: Database connection failed! Details: {e}")
    else:
        print("⚠️ WARNING: No DATABASE_URL found in environment variables.")
    yield

# --- 3. APP INITIALIZATION ---
app = FastAPI(title="NEPSE Diary API", version="1.0", lifespan=lifespan)

# Allow all origins so you can fetch data from your laptop, mobile, or any frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["GET"], # STRICT READ-ONLY SECURITY
    allow_headers=["*"],
)

# --- 4. THE UNIVERSAL DATA FETCHER ---
def fetch_read_only_data(table_name: str, order_by: str = None):
    if not engine:
        raise HTTPException(status_code=500, detail="Database URL not configured on server.")
        
    try:
        with engine.connect() as conn:
            # Safely target the public schema to bypass Connection Pooler routing issues
            query_string = f"SELECT * FROM public.{table_name}"
            if order_by:
                query_string += f" ORDER BY {order_by}"
                
            query = text(query_string)
            df = pd.read_sql(query, con=conn)
        
        # Format common date columns safely for JSON
        date_columns = ['date', 'created_at', 'updated_at']
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col]).dt.strftime('%Y-%m-%d')
                
        # Prevent JSON crashes on empty database cells
        df = df.fillna("")
        
        data = df.to_dict(orient="records")
        return {"status": "success", "table": table_name, "count": len(data), "data": data}
        
    except Exception as e:
        print(f"\n❌ CRASH on table '{table_name}': {str(e)}\n")
        raise HTTPException(status_code=500, detail=f"Failed to read {table_name}: {str(e)}")

# --- 5. THE ENDPOINTS (ALL 8 TABLES) ---

@app.get("/")
def read_root():
    return {"message": "NEPSE Diary API is Live. All endpoints are Read-Only."}

@app.get("/api/portfolio")
def get_portfolio():
    return fetch_read_only_data("portfolio", order_by="date DESC")

@app.get("/api/audit_log")
def get_audit_log():
    return fetch_read_only_data("audit_log")

@app.get("/api/cache")
def get_cache():
    return fetch_read_only_data("cache")

@app.get("/api/history")
def get_history():
    return fetch_read_only_data("history")

@app.get("/api/tms_trx")
def get_tms_trx():
    return fetch_read_only_data("tms_trx")

@app.get("/api/trading_journal")
def get_trading_journal():
    return fetch_read_only_data("trading_journal")

@app.get("/api/watchlist")
def get_watchlist():
    return fetch_read_only_data("watchlist")

@app.get("/api/wealth")
def get_wealth():
    return fetch_read_only_data("wealth")
