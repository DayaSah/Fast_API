import os
import requests
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

router = APIRouter()

# --- CONFIGURATION ---
# These must be set in your Render Environment Variables
GITHUB_PAT = os.getenv("GITHUB_PAT")
REPO_OWNER = "DayaSah"
REPO_NAME = "My_Nepse_Diary"
WORKFLOW_ID = "LTP_sync.yml"

@router.post("/refresh-ltp")
async def trigger_github_sync():
    """
    Dispatches a repository_dispatch event to GitHub Actions 
    to trigger the LTP_sync.yml workflow.
    """
    if not GITHUB_PAT:
        raise HTTPException(status_code=500, detail="GITHUB_PAT not configured on server.")

    # GitHub API URL for Repository Dispatch
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/dispatches"

    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # 'event_type' must match the 'types' under 'repository_dispatch' in your YAML
    data = {
        "event_type": "trigger-ltp-sync", 
        "client_payload": {
            "origin": "FastAPI_Render_Terminal"
        }
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        
        # GitHub returns 204 No Content on successful dispatch
        if response.status_code == 204:
            return {
                "status": "success",
                "message": "GitHub Workflow dispatched successfully. Prices will update in ~1 minute.",
                "target_repo": f"{REPO_OWNER}/{REPO_NAME}"
            }
        else:
            return {
                "status": "error",
                "code": response.status_code,
                "detail": response.text
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to communicate with GitHub: {str(e)}")
