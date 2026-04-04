import os
import requests
from fastapi import APIRouter, HTTPException

router = APIRouter()

# These must be set in Render Environment Variables
GITHUB_PAT = os.getenv("GITHUB_PAT") 
REPO_OWNER = "DayaSah"
REPO_NAME = "My_Nepse_Diary"

@router.post("/refresh-ltp", tags=["System"])
async def trigger_github_refresh():
    if not GITHUB_PAT:
        raise HTTPException(status_code=500, detail="GITHUB_PAT not found in Environment Variables")

    # GitHub API endpoint to trigger a 'repository_dispatch'
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/dispatches"
    
    headers = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    # 'event_type' must match the YAML file in Step 2
    payload = {"event_type": "trigger_nepse_sync"}

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 204:
            return {"status": "success", "message": "GitHub Action triggered!"}
        else:
            return {"status": "error", "detail": response.text}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
