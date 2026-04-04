import os
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

# --- DATABASE ENGINE ---
from database import get_db_engine

# --- ROUTER IMPORTS ---
# We rename them during import to avoid "router" name collisions
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

# APP INITIALIZATION
app = FastAPI(
    title="NEPSE Diary API", 
    lifespan=lifespan, 
    docs_url="/docs", # Set to None in production if you want to hide it
    redoc_url=None
)

# --- CORS SECURITY ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (good for development)
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"], 
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "message": "NEPSE Diary Cloud API is Live.",
        "endpoints": ["/api/active_portfolio", "/api/trade_history", "/api/sync"]
    }

# --- GITHUB ACTION SYNC ENDPOINT ---
@app.post("/api/sync")
async def trigger_github_action():
    github_pat = os.getenv("GITHUB_PAT")
    
    if not github_pat:
        raise HTTPException(status_code=500, detail="Server misconfiguration: GITHUB_PAT missing.")

    repo_owner = "DayaSah"
    repo_name = "My_Nepse_Diary"
    workflow_file = "daily_sync.yml"
    
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/workflows/{workflow_file}/dispatches"

    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    try:
        response = requests.post(url, headers=headers, json={"ref": "main"})
        if response.status_code == 204:
            return {"status": "success", "message": "Sync triggered successfully."}
        else:
            raise HTTPException(status_code=502, detail=f"GitHub Error: {response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- PLUG IN THE ROUTERS ---
# All your Live Market and WACC math
app.include_router(active_portfolio_router, prefix="/api", tags=["Analytics"])

# All your FIFO Trade History and Settlement math
app.include_router(history_router, prefix="/api", tags=["History"])

# Manual Refresh Endpoint
app.include_router(refresh_router, prefix="/api")
