from fastapi import APIRouter, HTTPException, Depends
import pandas as pd
from sqlalchemy import text
from database import get_db_engine

# Create a router specifically for these raw tables
router = APIRouter()

def fetch_read_only_data(table_name: str, engine, order_by: str = None):
    if not engine:
        raise HTTPException(status_code=500, detail="Database URL not configured.")
        
    try:
        with engine.connect() as conn:
            query_string = f"SELECT * FROM public.{table_name}"
            if order_by:
                query_string += f" ORDER BY {order_by}"
                
            query = text(query_string)
            df = pd.read_sql(query, con=conn)
        
        date_columns = ['date', 'created_at', 'updated_at']
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col]).dt.strftime('%Y-%m-%d')
                
        df = df.fillna("")
        data = df.to_dict(orient="records")
        return {"status": "success", "table": table_name, "count": len(data), "data": data}
        
    except Exception as e:
        print(f"\n❌ CRASH on table '{table_name}': {str(e)}\n")
        raise HTTPException(status_code=500, detail=f"Failed to read {table_name}")

# --- THE 8 ENDPOINTS ---
@router.get("/portfolio")
def get_portfolio(engine = Depends(get_db_engine)):
    return fetch_read_only_data("portfolio", engine, order_by="date DESC")

@router.get("/audit_log")
def get_audit_log(engine = Depends(get_db_engine)):
    return fetch_read_only_data("audit_log", engine)

@router.get("/cache")
def get_cache(engine = Depends(get_db_engine)):
    return fetch_read_only_data("cache", engine)

@router.get("/history")
def get_history(engine = Depends(get_db_engine)):
    return fetch_read_only_data("history", engine)

@router.get("/tms_trx")
def get_tms_trx(engine = Depends(get_db_engine)):
    return fetch_read_only_data("tms_trx", engine)

@router.get("/trading_journal")
def get_trading_journal(engine = Depends(get_db_engine)):
    return fetch_read_only_data("trading_journal", engine)

@router.get("/watchlist")
def get_watchlist(engine = Depends(get_db_engine)):
    return fetch_read_only_data("watchlist", engine)

@router.get("/wealth")
def get_wealth(engine = Depends(get_db_engine)):
    return fetch_read_only_data("wealth", engine)
