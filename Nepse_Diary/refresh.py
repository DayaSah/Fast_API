import os
import requests
import datetime
import pytz
from fastapi import APIRouter, HTTPException

router = APIRouter()

# These must be set in Render Environment Variables
GITHUB_PAT = os.getenv("GITHUB_PAT") 
REPO_OWNER = "DayaSah"
REPO_NAME = "My_Nepse_Diary"

@router.post("/refresh-ltp", tags=["System"])
async def trigger_github_refresh():
    """
    This endpoint 'pings' GitHub Actions to run the scraper.
    """
    if not GITHUB_PAT:
        raise HTTPException(status_code=500, detail="GITHUB_PAT not found in Render Env Vars")

    nepal_tz = pytz.timezone('Asia/Kathmandu')
    now = datetime.datetime.now(nepal_tz).strftime("%H:%M:%S")

    # GitHub API URL
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/dispatches"
    
    headers = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    # CRITICAL: 'event_type' must match the 'types' in your .yml file
    payload = {
        "event_type": "trigger_nepse_sync",
        "client_payload": {"triggered_at": now}
    }

    try:
        # Use a short timeout here so the API responds quickly
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 204:
            return {
                "status": "success",
                "message": "GitHub Action (LTP_sync.yml) triggered!",
                "requested_at": now
            }
        else:
            return {
                "status": "error", 
                "github_response": response.text,
                "status_code": response.status_code
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection to GitHub failed: {str(e)}")
