import os
import requests
import datetime
import pytz
from fastapi import APIRouter, HTTPException

router = APIRouter()

# Environment Variables from Render
GITHUB_PAT = os.getenv("GITHUB_PAT")
REPO_OWNER = "DayaSah"
REPO_NAME = "My_Nepse_Diary"

@router.post("/refresh-ltp")
async def trigger_github_refresh():
    """
    Triggers the GitHub Action 'LTP_sync.yml' using Repository Dispatch.
    """
    if not GITHUB_PAT:
        raise HTTPException(
            status_code=500, 
            detail="GITHUB_PAT is missing in Render environment variables."
        )

    nepal_tz = pytz.timezone('Asia/Kathmandu')
    now = datetime.datetime.now(nepal_tz).strftime("%H:%M:%S")

    # The Repository Dispatch URL (Signals the whole repo)
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/dispatches"
    
    headers = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    # 'event_type' matches the 'types' in your LTP_sync.yml
    payload = {
        "event_type": "trigger_nepse_sync",
        "client_payload": {"triggered_at": now}
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        # GitHub returns 204 No Content on a successful dispatch
        if response.status_code == 204:
            return {
                "status": "success",
                "message": "GitHub Action triggered successfully.",
                "timestamp": now
            }
        else:
            return {
                "status": "github_error",
                "code": response.status_code,
                "detail": response.text
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to GitHub: {str(e)}")
