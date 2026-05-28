"""
phase3_api_test.py
Validate SAM.gov API match quality on 10 known universities before running full enrichment.
Tests: correct match, wrong match, sub-entity match, rate limit behavior.
"""

import json
import os
import time
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SAM_GOV_API_KEY")
SAM_URL = "https://api.sam.gov/entity-information/v3/entities"
DELAY   = 1.5   # conservative rate limit delay

TEST_CASES = [
    # (query_name, query_state, expected_uei_or_keyword_in_name)
    ("University of North Texas",            "TX", "NORTH TEXAS"),
    ("UNIVERSITY OF NORTH TEXAS",            "TX", "NORTH TEXAS"),   # ALL CAPS variant
    ("Texas A&M University",                 "TX", "TEXAS A&M"),
    ("University of Texas at Austin",        "TX", "TEXAS AT AUSTIN"),
    ("Stanford University",                  "CA", "STANFORD"),
    ("Yale University",                      "CT", "YALE"),
    ("University of Michigan",               "MI", "MICHIGAN"),
    ("UNIVERSITY OF MICHIGAN AT ANN ARBOR",  "MI", "MICHIGAN"),      # long variant
    ("University of Pennsylvania",           "PA", "PENNSYLVANIA"),  # NOT Clarion
    ("Purdue University",                    "IN", "PURDUE"),
]


def samgov_lookup(name: str) -> list[dict]:
    params = {
        "legalBusinessName": name,
        "includeSections": "entityRegistration,coreData",
        "api_key": API_KEY,
    }
    url = f"{SAM_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
            data = json.loads(resp.read())
        return [
            {
                "uei":   e.get("entityRegistration", {}).get("ueiSAM"),
                "name":  e.get("entityRegistration", {}).get("legalBusinessName"),
                "state": e.get("coreData", {}).get("physicalAddress", {}).get("stateOrProvinceCode"),
            }
            for e in (data.get("entityData") or [])
        ]
    except urllib.error.HTTPError as ex:
        return [{"error": f"HTTP {ex.code}"}]
    except Exception as ex:
        return [{"error": str(ex)}]


def run():
    print(f"Testing SAM.gov API with {len(TEST_CASES)} known institutions\n")
    print(f"{'Query':<45} {'Top Result':<45} {'State':<6} {'Pass?'}")
    print("-" * 110)

    for query, state, expected_kw in TEST_CASES:
        candidates = samgov_lookup(query)
        time.sleep(DELAY)

        if not candidates:
            result_name = "NO RESULTS"
            result_state = ""
            passed = "FAIL NO RESULTS"
        elif "error" in candidates[0]:
            result_name = candidates[0]["error"]
            result_state = ""
            passed = "FAIL ERROR"
        else:
            top = candidates[0]
            result_name  = (top.get("name") or "")[:44]
            result_state = top.get("state") or ""
            name_ok  = expected_kw.upper() in (top.get("name") or "").upper()
            state_ok = result_state.upper() == state.upper()
            passed   = "OK" if (name_ok and state_ok) else f"FAIL (name={'ok' if name_ok else 'WRONG'}, state={'ok' if state_ok else 'WRONG'})"

        print(f"{query:<45} {result_name:<45} {result_state:<6} {passed}")

        # Show all candidates if top result looks wrong
        if "FAIL" in str(passed) and candidates and "error" not in candidates[0]:
            print(f"  All candidates ({len(candidates)}):")
            for c in candidates[:5]:
                print(f"    {c.get('uei')}  {c.get('state')}  {c.get('name')}")
        print()


if __name__ == "__main__":
    run()
