import os
import requests
from fastapi import APIRouter, HTTPException

router = APIRouter()

# Constants
GITHUB_PAT = os.getenv("GITHUB_PAT")
REPO_OWNER = "DayaSah"
REPO_NAME = "My_Nepse_Diary"

@router.post("/refresh-ltp")
async def trigger_github_sync():
    if not GITHUB_PAT:
        raise HTTPException(status_code=500, detail="Missing GITHUB_PAT in Environment Variables")

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/dispatches"
    
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
    }

    # IMPORTANT: event_type must match the 'types' in the YAML above
    data = {
        "event_type": "trigger-ltp-sync",
        "client_payload": {"triggered_by": "FastAPI-Terminal"}
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 204:
            return {"status": "success", "message": "Sync Dispatched to GitHub Actions."}
        else:
            return {"status": "error", "message": response.text}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
