import requests
import json
from datetime import datetime
import time
import sys
import os

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN")
REPO_OWNER = "xiajd-we1"
REPO_NAME = "cfnb"
WORKFLOW_ID = "280559335"

def trigger_workflow():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{WORKFLOW_ID}/dispatches"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "ref": "main"
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 204:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Workflow triggered successfully!")
            return True
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Failed to trigger workflow")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Error: {e}")
        return False

def main():
    print("="*60)
    print("Cloudflare IP Auto-Updater (External Cron)")
    print("="*60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Target: {REPO_OWNER}/{REPO_NAME}")
    print(f"Workflow: {WORKFLOW_ID}")
    print("="*60)
    
    if GITHUB_TOKEN == "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN":
        print("❌ ERROR: Please set your GitHub Personal Access Token!")
        print("")
        print("Steps to get token:")
        print("1. Go to https://github.com/settings/tokens")
        print("2. Click 'Generate new token (classic)'")
        print("3. Check 'repo' scope")
        "4. Generate and copy the token"
        print("5. Replace YOUR_GITHUB_PERSONAL_ACCESS_TOKEN in this script")
        sys.exit(1)
    
    success = trigger_workflow()
    
    if success:
        print("\n✅ Done! The workflow will start running on GitHub.")
        print("Check https://github.com/xiajd-we1/cfnb/actions for progress")
    else:
        print("\n❌ Failed! Please check your token and network.")
    
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())
