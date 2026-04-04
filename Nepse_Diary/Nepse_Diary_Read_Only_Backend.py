import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

# --- DATABASE ENGINE ---
from database import get_db_engine

# --- ROUTER IMPORTS ---
from active_portfolio import router as active_portfolio_router
from history import router as history_router
from refresh import router as refresh_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n--- NEPSE Diary Cloud API Starting Up ---")
    engine = get_db_engine()
    if engine:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("✅ SUCCESS: Connected to Neon PostgreSQL!")
        except Exception as e:
            print(f"❌ ERROR: Database connection failed! Details: {e}")
    yield

app = FastAPI(
    title="NEPSE Diary API", 
    lifespan=lifespan, 
    docs_url="/docs",
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"], 
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "message": "NEPSE Diary Cloud API is Live.",
        "endpoints": ["/api/active_portfolio", "/api/trade_history", "/api/refresh-ltp"]
    }

# --- PLUG IN THE ROUTERS ---
app.include_router(active_portfolio_router, prefix="/api", tags=["Analytics"])
app.include_router(history_router, prefix="/api", tags=["History"])
app.include_router(refresh_router, prefix="/api", tags=["System"]) # GitHub Trigger lives here
