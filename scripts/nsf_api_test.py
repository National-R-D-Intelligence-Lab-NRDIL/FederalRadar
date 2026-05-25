"""
nsf_api_test.py
Fetches two NSF awards from the public API and prints the full responses.
No database writes.
"""

import json
import urllib.request

BASE_URL = "https://api.nsf.gov/services/v1/awards.json"
AWARD_IDS = ["2531827", "2552363"]


def fetch_award(award_id: str) -> dict:
    url = f"{BASE_URL}?id={award_id}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())


def main():
    for award_id in AWARD_IDS:
        print(f"\n{'='*60}")
        print(f"Award ID: {award_id}")
        print(f"{'='*60}")
        data = fetch_award(award_id)
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
