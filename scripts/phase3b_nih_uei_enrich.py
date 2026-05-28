"""
phase3b_nih_uei_enrich.py
Enrich NIH records with UEI using two fast steps:

Step 1 - Cross-source name match (no API):
  Any NIH institution name that appears in NSF or USASpending with a known UEI
  gets that UEI propagated instantly. Done in Python with dict lookups.

Step 2 - NIH RePORTER API (free, no key, no rate limit):
  For remaining unmatched names, query NIH's own API (1 call per distinct name,
  limit=1). NIH returns primary_uei directly for each institution.
  Only university-like names are looked up; small businesses are skipped.
"""

import json
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH  = Path(__file__).parent.parent / "data" / "federal_awards.db"
NIH_URL  = "https://api.reporter.nih.gov/v2/projects/search"
DELAY    = 0.15   # seconds between NIH API calls (~6/sec, well within limits)
TIMEOUT  = 15

UNIVERSITY_KEYWORDS = [
    'UNIVERSITY', 'COLLEGE', 'INSTITUTE OF TECHNOLOGY',
    'POLYTECHNIC', 'SCHOOL OF', 'SEMINARY', 'CONSERVATORY',
]


def looks_like_university(name: str) -> bool:
    n = name.upper()
    return any(k in n for k in UNIVERSITY_KEYWORDS)


def nih_lookup(org_name: str) -> str | None:
    """Query NIH RePORTER for one institution name. Returns primary_uei or None."""
    payload = json.dumps({
        "criteria": {"org_names": [org_name]},
        "limit": 1,
        "offset": 0,
        "fields": ["organization"]
    }).encode()
    req = urllib.request.Request(
        NIH_URL, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
        results = data.get("results") or []
        if results:
            return results[0].get("organization", {}).get("primary_uei")
    except Exception:
        pass
    return None


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # -- Pre-flight counts --------------------------------------------------
    total_nih = conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'nih'"
    ).fetchone()[0]
    already_have_uei = conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'nih' AND inst_uei IS NOT NULL"
    ).fetchone()[0]
    print(f"NIH records:       {total_nih:,}")
    print(f"Already have UEI:  {already_have_uei:,}")

    # -- Step 1: build name->UEI map from all non-NIH records ---------------
    print("\nStep 1: Building name->UEI map from NSF + USASpending records...")
    name_to_uei: dict[str, str] = {}
    rows = conn.execute("""
        SELECT DISTINCT UPPER(inst_name), inst_uei
        FROM awards
        WHERE source != 'nih'
        AND inst_uei IS NOT NULL AND inst_uei != ''
        AND inst_name IS NOT NULL AND inst_name != ''
    """).fetchall()
    for upper_name, uei in rows:
        name_to_uei[upper_name] = uei
    print(f"  {len(name_to_uei):,} name->UEI mappings loaded")

    # -- Step 2: get distinct NIH names that still need UEI -----------------
    nih_names = conn.execute("""
        SELECT DISTINCT inst_name, inst_state_code
        FROM awards
        WHERE source = 'nih'
        AND (inst_uei IS NULL OR inst_uei = '')
        AND inst_name IS NOT NULL AND inst_name != ''
    """).fetchall()
    print(f"  Distinct NIH names needing UEI: {len(nih_names):,}")

    # -- Step 3: resolve via cross-source match -----------------------------
    cross_matched: dict[str, str] = {}
    still_need_api: list[tuple[str, str | None]] = []

    for name, state in nih_names:
        uei = name_to_uei.get(name.upper())
        if uei:
            cross_matched[name] = uei
        else:
            still_need_api.append((name, state))

    print(f"  Cross-source matched (no API): {len(cross_matched):,}")
    print(f"  Still need NIH API:            {len(still_need_api):,}")

    # Apply cross-source matches in bulk
    if cross_matched:
        print("\nApplying cross-source matches...")
        t0 = time.time()
        conn.executemany("""
            UPDATE awards SET inst_uei = ?
            WHERE source = 'nih' AND UPPER(inst_name) = UPPER(?)
            AND (inst_uei IS NULL OR inst_uei = '')
        """, [(uei, name) for name, uei in cross_matched.items()])
        conn.commit()
        print(f"  Done in {time.time()-t0:.1f}s")

    # -- Step 4: NIH API for remaining university-like names ----------------
    uni_names   = [(n, s) for n, s in still_need_api if looks_like_university(n)]
    other_names = [(n, s) for n, s in still_need_api if not looks_like_university(n)]
    print(f"\nStep 4: NIH API lookups")
    print(f"  University-like names: {len(uni_names):,}")
    print(f"  Non-university (skip): {len(other_names):,}")
    print(f"  Estimated time: ~{len(uni_names)*DELAY/60:.1f} min\n")

    api_matched = 0
    api_no_match = 0
    api_errors = 0
    api_results: dict[str, str] = {}

    for i, (name, state) in enumerate(uni_names, 1):
        uei = nih_lookup(name)
        time.sleep(DELAY)

        if uei:
            api_results[name] = uei
            api_matched += 1
        else:
            api_no_match += 1

        if i % 100 == 0 or i == len(uni_names):
            pct = i / len(uni_names) * 100
            print(f"  [{i:>4}/{len(uni_names)}] {pct:.0f}%  "
                  f"matched={api_matched}  no_match={api_no_match}")

    # Apply API matches in bulk
    if api_results:
        conn.executemany("""
            UPDATE awards SET inst_uei = ?
            WHERE source = 'nih' AND UPPER(inst_name) = UPPER(?)
            AND (inst_uei IS NULL OR inst_uei = '')
        """, [(uei, name) for name, uei in api_results.items()])
        conn.commit()

    # -- Final coverage report ----------------------------------------------
    row = conn.execute("""
        SELECT COUNT(*), COUNT(inst_uei), COUNT(*) - COUNT(inst_uei)
        FROM awards WHERE source = 'nih'
    """).fetchone()
    print(f"""
{'='*50}
NIH ENRICHMENT COMPLETE
{'='*50}
Cross-source matched:  {len(cross_matched):,}
NIH API matched:       {api_matched:,}
Non-university skip:   {len(other_names):,}
No match found:        {api_no_match:,}
{'='*50}
Final NIH coverage:
  Total:   {row[0]:,}
  Has UEI: {row[1]:,}  ({row[1]/row[0]*100:.1f}%)
  Missing: {row[2]:,}
""")

    # Spot check peer institutions
    print("Spot check - peer institutions:")
    peers = [
        "UNIVERSITY OF NORTH TEXAS",
        "TEXAS A&M UNIVERSITY",
        "UNIVERSITY OF TEXAS AT AUSTIN",
        "ARIZONA STATE UNIVERSITY",
        "PURDUE UNIVERSITY",
        "TULANE UNIVERSITY",
        "UNIVERSITY OF ILLINOIS CHICAGO",
        "UNIVERSITY OF CALIFORNIA RIVERSIDE",
    ]
    for name in peers:
        row = conn.execute("""
            SELECT inst_uei FROM awards
            WHERE source = 'nih' AND UPPER(inst_name) = ?
            AND inst_uei IS NOT NULL LIMIT 1
        """, (name,)).fetchone()
        status = row[0] if row else "NOT FOUND"
        print(f"  {name:<45} {status}")

    conn.close()
    print("\nPhase 3b complete.")


if __name__ == "__main__":
    run()
