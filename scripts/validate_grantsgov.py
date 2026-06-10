"""
Validate open opportunities from JSONL against Grants.gov live API.
Compares title, agency, CFDA, status for 5 sample records.
"""

import urllib.request
import json

JSONL = "data/grants_gov/raw/2026-06-04_all.jsonl"
API   = "https://api.grants.gov/v1/api/search2"


def api_lookup(opp_number):
    payload = json.dumps({"oppNum": opp_number, "rows": 1}).encode()
    req = urllib.request.Request(API, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    hits = data["data"].get("oppHits", [])
    return hits[0] if hits else None


def normalize_cfda(val):
    if isinstance(val, list):
        return sorted(val)
    if isinstance(val, str):
        return sorted([x.strip() for x in val.split(",")])
    return []


local_recs = []
with open(JSONL, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if rec["derived_status"] == "open" and rec.get("CFDANumbers"):
            local_recs.append(rec)
            if len(local_recs) >= 5:
                break

print("=== VALIDATION: JSONL vs Grants.gov API ===\n")
mismatches = 0

for local in local_recs:
    opp_num = local.get("OpportunityNumber", "")
    opp_id  = local.get("OpportunityID", "")
    api     = api_lookup(opp_num)

    print(f"Opportunity: {opp_num}  (ID: {opp_id})")

    if not api:
        print("  NOT FOUND in API")
        mismatches += 1
    else:
        checks = [
            ("title",   local.get("OpportunityTitle", "")[:60],
                        api.get("title", "")[:60]),
            ("agency",  local.get("AgencyCode", ""),
                        api.get("agencyCode", "")),
            ("status",  "posted",
                        api.get("oppStatus", "")),
            ("cfda",    str(normalize_cfda(local.get("CFDANumbers"))),
                        str(normalize_cfda(api.get("cfdaList")))),
        ]
        for field, lval, aval in checks:
            match = "OK" if str(lval).lower() == str(aval).lower() else "MISMATCH"
            print(f"  [{match}] {field:<8}  JSONL: {lval!r}")
            if match == "MISMATCH":
                print(f"           {'':8}  API:   {aval!r}")
                mismatches += 1
    print()

print(f"Result: {mismatches} mismatches across 5 records")
