from fastapi import APIRouter, BackgroundTasks
from active_portfolio import update_chukul_local_job, LOCAL_MARKET_CACHE
import datetime
import pytz

router = APIRouter()

@router.post("/refresh-ltp", tags=["System"])
async def manual_refresh(background_tasks: BackgroundTasks):
    """
    Manually triggers the Chukul LTP sync.
    Uses BackgroundTasks so the API responds immediately while the fetch happens.
    """
    nepal_tz = pytz.timezone('Asia/Kathmandu')
    now = datetime.datetime.now(nepal_tz).strftime("%H:%M:%S")
    
    # We run this as a background task so the user doesn't have to wait for the 
    # external API request to finish before getting a 'Success' response.
    
    # force+True
    background_tasks.add_task(update_chukul_local_job, force=True)
    
    return {
        "status": "refresh_triggered",
        "requested_at": now,
        "current_cache_status": LOCAL_MARKET_CACHE["status"],
        "last_sync_was": LOCAL_MARKET_CACHE["last_updated"]
    }
