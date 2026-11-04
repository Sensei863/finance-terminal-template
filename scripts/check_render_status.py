import os
import requests
from dotenv import load_dotenv

def check_render_status():
    load_dotenv()
    
    api_key = os.getenv("RENDER_API_KEY")
    service_id = os.getenv("RENDER_SERVICE_ID")
    
    if not api_key or not service_id:
        print("Missing RENDER_API_KEY or RENDER_SERVICE_ID in .env")
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }

    # Fetch latest deploys
    url = f"https://api.render.com/v1/services/{service_id}/deploys?limit=1"
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        deploys = response.json()
        if deploys:
            latest = deploys[0]["deploy"]
            print(f"Latest Deploy ID: {latest['id']}")
            print(f"Status: {latest['status']}")
            print(f"Trigger: {latest['trigger']}")
            print(f"Commit Message: {latest['commit']['message']}")
            print(f"Updated At: {latest['updatedAt']}")
        else:
            print("No deploys found.")
    else:
        print(f"Failed to fetch deploys. Status code: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    check_render_status()
