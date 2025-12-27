
import requests
import json

ENDPOINTS = [
    "https://data-api.polymarket.com/leaderboard?min_volume=1000",
    "https://data-api.polymarket.com/v1/leaderboard",
    "https://gamma-api.polymarket.com/leaderboard",
    "https://clob.polymarket.com/leaderboard"
]

def check():
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in ENDPOINTS:
        try:
            print(f"Checking {url}...")
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                print(f"SUCCESS: {url}")
                print(json.dumps(data[:2] if isinstance(data, list) else data, indent=2))
                return
            else:
                print(f"FAILED ({resp.status_code})")
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    check()
