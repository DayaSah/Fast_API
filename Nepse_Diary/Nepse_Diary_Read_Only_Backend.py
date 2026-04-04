import os
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

# Import our database and the specific router you need
from database import get_db_engine
# Only keeping the active_portfolio_router as requested
from active_portfolio import router as active_portfolio_router

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
app = FastAPI(title="NEPSE Diary API", lifespan=lifespan, docs_url=None, redoc_url=None)

# --- CORS SECURITY ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"], 
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Active Portfolio API is Live."}

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

# --- PLUG IN THE ACTIVE PORTFOLIO ROUTER ---
# REMOVED: raw_tables_router and trade_history_router (to fix the NameError)
app.include_router(active_portfolio_router, prefix="/api", tags=["Analytics"])
app.include_router(history.router, prefix="/api")
