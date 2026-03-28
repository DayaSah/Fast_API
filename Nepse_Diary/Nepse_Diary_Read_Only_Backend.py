import os
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

# Import our database and routers
from database import get_db_engine
from raw_tables import router as raw_tables_router
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

# APP INITIALIZATION (Docs Disabled for Security)
app = FastAPI(title="Master API Gateway", lifespan=lifespan, docs_url=None, redoc_url=None)

# --- STRICT CORS SECURITY ---
# Replace with your actual frontend URL (e.g., "https://dayasah.github.io")
ALLOWED_FRONTEND_URL = "https://dayasah.github.io" 

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_FRONTEND_URL], 
    allow_credentials=True,
    # CRITICAL FIX: Added POST and OPTIONS so the Sync button is allowed to communicate
    allow_methods=["GET", "POST", "OPTIONS"], 
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Master API is Live. Unauthorized access is restricted."}

# --- GITHUB ACTION SYNC ENDPOINT (Serverless Trigger) ---
@app.post("/api/sync")
async def trigger_github_action():
    # 1. Grab the secure token from Render Environment Variables
    github_pat = os.getenv("GITHUB_PAT")
    
    if not github_pat:
        print("❌ ERROR: GITHUB_PAT environment variable is missing on Render!")
        raise HTTPException(status_code=500, detail="Server misconfiguration: GITHUB_PAT missing.")

    # 2. Target your specific repository and workflow
    repo_owner = "DayaSah"
    repo_name = "My_Nepse_Diary"
    workflow_file = "daily_sync.yml"
    
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/workflows/{workflow_file}/dispatches"

    # 3. Setup authentication
    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # 4. Point to the 'main' branch (change to 'master' if your repo uses master)
    data = {
        "ref": "main" 
    }

    # 5. Execute the trigger
    try:
        response = requests.post(url, headers=headers, json=data)
        
        # 204 No Content is GitHub's success code for this specific API
        if response.status_code == 204:
            return {"status": "success", "message": "GitHub Action triggered successfully. Syncing Data..."}
        else:
            print(f"❌ GitHub API Error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=502, detail="Failed to trigger GitHub Action. Check Render logs.")
            
    except Exception as e:
        print(f"❌ Server Error Triggering Sync: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while contacting GitHub.")

# --- PLUG IN THE ROUTERS ---
# This makes them accessible at /api/portfolio, /api/active_portfolio, etc.
app.include_router(raw_tables_router, prefix="/api", tags=["Raw Data"])
app.include_router(active_portfolio_router, prefix="/api", tags=["Analytics"])
