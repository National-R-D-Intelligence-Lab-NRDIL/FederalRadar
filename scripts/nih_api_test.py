"""
nih_api_test.py
Test script: hit NIH RePORTER API and print raw + summary for UNT awards.
No database writes.
"""

import json
import urllib.request

URL = "https://api.reporter.nih.gov/v2/projects/search"
PAYLOAD = {
    "criteria": {
        "fiscal_years": [2025],
        "org_names": ["University of North Texas"],
    },
    "limit": 5,
    "offset": 0,
}


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def main():
    data = post_json(URL, PAYLOAD)
    results = data.get("results") or []

    # --- Full raw JSON for first result ---
    print("=" * 80)
    print("RAW JSON — FIRST RESULT")
    print("=" * 80)
    if results:
        print(json.dumps(results[0], indent=2))
    else:
        print("No results returned.")
        return

    # --- Summary for all 5 results ---
    print("\n" + "=" * 80)
    print(f"SUMMARY — {len(results)} RESULT(S)")
    print("=" * 80)

    for i, r in enumerate(results, 1):
        org  = r.get("organization") or {}
        pis  = r.get("principal_investigators") or []
        pi_names = ", ".join(
            f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            for p in pis
        ) or "N/A"
        abstract = (r.get("abstract_text") or "")[:200]

        print(f"\n--- Result {i} ---")
        print(f"  project_num        : {r.get('project_num')}")
        print(f"  project_title      : {r.get('project_title')}")
        print(f"  fiscal_year        : {r.get('fiscal_year')}")
        print(f"  award_amount       : {r.get('award_amount')}")
        print(f"  activity_code      : {r.get('activity_code')}")
        print(f"  project_start_date : {r.get('project_start_date')}")
        print(f"  project_end_date   : {r.get('project_end_date')}")
        print(f"  abstract_text      : {abstract!r}")
        print(f"  agency_ic_fundings : {r.get('agency_ic_fundings')}")
        print(f"  pi_names           : {pi_names}")
        print(f"  org_name           : {org.get('org_name')}")
        print(f"  org_state          : {org.get('org_state')}")


if __name__ == "__main__":
    main()
