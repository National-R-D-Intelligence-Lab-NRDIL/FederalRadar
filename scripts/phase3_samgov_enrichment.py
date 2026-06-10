"""
phase3_samgov_enrichment.py
Enrich NSF/NIH institution records with UEIs from SAM.gov.

Strategy:
1. Name-match NSF/NIH institution names against existing institutions table (fast, no API)
2. For unmatched university-like names, look up via SAM.gov entity search API
3. Write all results to institutions_samgov_staging for review before committing
4. Safe to re-run: clears staging table each run

Run:  python scripts/phase3_samgov_enrichment.py
Then: python scripts/phase3_review_staging.py   (to inspect before committing)
Then: python scripts/phase3_commit_enrichment.py (to write UEIs to awards table)
"""

import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(__file__).parent.parent / "data" / "federal_awards.db"
API_KEY = os.getenv("SAM_GOV_API_KEY")
SAM_URL = "https://api.sam.gov/entity-information/v3/entities"
RATE_LIMIT_DELAY = 0.5   # seconds between calls (2/sec, well under limit)
REQUEST_TIMEOUT  = 15    # seconds

UNIVERSITY_KEYWORDS = [
    'UNIVERSITY', 'COLLEGE', 'INSTITUTE OF TECHNOLOGY', 'POLYTECHNIC',
    'SCHOOL OF', 'ACADEMY', 'SEMINARY', 'CONSERVATORY',
]


def looks_like_university(name: str) -> bool:
    n = name.upper()
    return any(kw in n for kw in UNIVERSITY_KEYWORDS)


def samgov_lookup(name: str, state: str | None = None) -> list[dict]:
    """Query SAM.gov for entities matching name. Returns list of candidate dicts."""
    params = {
        "legalBusinessName": name,
        "includeSections": "entityRegistration,coreData",
        "api_key": API_KEY,
    }
    url = f"{SAM_URL}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())
        candidates = []
        for e in (data.get("entityData") or []):
            reg  = e.get("entityRegistration", {})
            addr = e.get("coreData", {}).get("physicalAddress", {})
            candidates.append({
                "uei":   reg.get("ueiSAM"),
                "name":  reg.get("legalBusinessName"),
                "state": addr.get("stateOrProvinceCode"),
            })
        return candidates
    except Exception as ex:
        return [{"error": str(ex)}]


def score_match(query_name: str, query_state: str | None,
                candidate: dict) -> float:
    """Score 0–1: how well does a SAM.gov candidate match our query?"""
    if "error" in candidate or not candidate.get("uei"):
        return 0.0
    cname  = (candidate.get("name") or "").upper()
    qname  = query_name.upper()
    cstate = candidate.get("state") or ""
    score  = 0.0
    # Exact name match
    if cname == qname:
        score += 0.6
    elif qname in cname or cname in qname:
        score += 0.3
    # State match (if known)
    if query_state and cstate == query_state.upper():
        score += 0.3
    elif not query_state:
        score += 0.1   # can't penalise if we don't know state
    return score


def run():
    if not API_KEY:
        raise SystemExit("SAM_GOV_API_KEY not set — check your .env file")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")

    # ── Step 0: create/reset staging table ────────────────────────────────
    conn.execute("DROP TABLE IF EXISTS institutions_samgov_staging")
    conn.execute("""
        CREATE TABLE institutions_samgov_staging (
            inst_name_raw       TEXT NOT NULL,
            match_type          TEXT,   -- 'name_match', 'samgov_auto', 'samgov_ambiguous', 'no_match'
            inst_uei            TEXT,
            samgov_legal_name   TEXT,
            samgov_state        TEXT,
            match_score         REAL,
            candidates_json     TEXT,   -- full SAM.gov response for review
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("Staging table ready.")

    # ── Step 1: load existing institutions (for name-matching) ────────────
    existing = {}   # upper_name -> (uei, canonical_name)
    for uei, name in conn.execute(
        "SELECT inst_uei, canonical_name FROM institutions WHERE canonical_name IS NOT NULL"
    ):
        existing[name.upper()] = (uei, name)
    print(f"Loaded {len(existing):,} existing institutions for name matching.")

    # ── Step 2: get all distinct NSF/NIH institution names + their state ──
    names_states = conn.execute("""
        SELECT inst_name, inst_state_code,
               COUNT(*) as n
        FROM awards
        WHERE source IN ('nsf', 'nih')
        AND inst_name IS NOT NULL AND inst_name != ''
        GROUP BY inst_name, inst_state_code
        ORDER BY n DESC
    """).fetchall()

    # Deduplicate: for each inst_name, use the most common state
    name_to_state: dict[str, str | None] = {}
    for name, state, _ in names_states:
        if name not in name_to_state:
            name_to_state[name] = state
    print(f"Distinct NSF/NIH institution names: {len(name_to_state):,}")

    # ── Step 3: classify each name ────────────────────────────────────────
    to_lookup   = []
    name_match  = []
    non_uni     = []

    for name, state in name_to_state.items():
        if name.upper() in existing:
            uei, canon = existing[name.upper()]
            name_match.append((name, uei, canon, state))
        elif looks_like_university(name):
            to_lookup.append((name, state))
        else:
            non_uni.append(name)

    print(f"  Name-matched (no API):  {len(name_match):,}")
    print(f"  Need SAM.gov lookup:    {len(to_lookup):,}")
    print(f"  Non-university (skip):  {len(non_uni):,}")

    # ── Step 4: insert name-match results into staging ────────────────────
    conn.executemany("""
        INSERT INTO institutions_samgov_staging
            (inst_name_raw, match_type, inst_uei, samgov_legal_name, samgov_state, match_score)
        VALUES (?, 'name_match', ?, ?, ?, 1.0)
    """, [(name, uei, canon, state) for name, uei, canon, state in name_match])
    conn.commit()
    print(f"Inserted {len(name_match):,} name-match rows into staging.")

    # ── Step 5: SAM.gov lookups ───────────────────────────────────────────
    print(f"\nStarting SAM.gov lookups for {len(to_lookup):,} universities...")
    print("(Press Ctrl+C to stop — progress is saved to staging table)\n")

    auto_match  = 0
    ambiguous   = 0
    no_match    = 0
    errors      = 0

    for i, (name, state) in enumerate(to_lookup, 1):
        candidates = samgov_lookup(name, state)
        time.sleep(RATE_LIMIT_DELAY)

        if candidates and "error" in candidates[0]:
            match_type = "no_match"
            uei = canon = sam_state = None
            score = 0.0
            errors += 1
        elif not candidates:
            match_type = "no_match"
            uei = canon = sam_state = None
            score = 0.0
            no_match += 1
        else:
            # Score all candidates
            scored = sorted(
                [(score_match(name, state, c), i, c) for i, c in enumerate(candidates)],
                reverse=True
            )
            scored = [(s, c) for s, _, c in scored]
            best_score, best = scored[0]

            if best_score >= 0.6:
                match_type = "samgov_auto"
                uei        = best["uei"]
                canon      = best["name"]
                sam_state  = best["state"]
                score      = best_score
                auto_match += 1
            elif best_score >= 0.3:
                match_type = "samgov_ambiguous"
                uei        = best["uei"]
                canon      = best["name"]
                sam_state  = best["state"]
                score      = best_score
                ambiguous  += 1
            else:
                match_type = "no_match"
                uei = canon = sam_state = None
                score = best_score
                no_match += 1

        conn.execute("""
            INSERT INTO institutions_samgov_staging
                (inst_name_raw, match_type, inst_uei, samgov_legal_name,
                 samgov_state, match_score, candidates_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, match_type, uei, canon, sam_state, score,
              json.dumps(candidates)))
        conn.commit()

        if i % 50 == 0 or i == len(to_lookup):
            print(f"  [{i:>4}/{len(to_lookup)}]  "
                  f"auto={auto_match}  ambiguous={ambiguous}  "
                  f"no_match={no_match}  errors={errors}")

    # ── Step 6: Summary ───────────────────────────────────────────────────
    print(f"""
{'='*50}
PHASE 3 ENRICHMENT COMPLETE
{'='*50}
Name-matched (no API):   {len(name_match):,}
SAM.gov auto-matched:    {auto_match:,}
SAM.gov ambiguous:       {ambiguous:,}  ← review these
No match found:          {no_match:,}
Errors:                  {errors:,}
Non-university (skipped):{len(non_uni):,}
{'='*50}
Next step: python scripts/phase3_review_staging.py
""")
    conn.close()


if __name__ == "__main__":
    run()
