from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks, APIRouter
from sync import run_full_sync
from contextlib import asynccontextmanager
from sqlalchemy import text

# Import our database and routers
from database import get_db_engine
from raw_tables import router as raw_tables_router
from active_portfolio import router as active_portfolio_router


router = APIRouter()
@router.post("/api/sync")
async def trigger_manual_sync(background_tasks: BackgroundTasks):
    # This tells FastAPI to run this function after responding to the user
    background_tasks.add_task(run_full_sync)
    
    # The frontend gets this response instantly, preventing timeouts
    return {"status": "success", "message": "Sync initiated in the background. Data will update shortly."}


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
    allow_methods=["GET"], 
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Master API is Live. Unauthorized access is restricted."}

# --- PLUG IN THE ROUTERS ---
# This makes them accessible at /api/portfolio, /api/active_portfolio, etc.
app.include_router(raw_tables_router, prefix="/api", tags=["Raw Data"])
app.include_router(active_portfolio_router, prefix="/api", tags=["Analytics"])
