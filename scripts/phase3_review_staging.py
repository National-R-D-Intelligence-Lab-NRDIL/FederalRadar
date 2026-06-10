"""
phase3_review_staging.py
Review the SAM.gov enrichment staging table before committing to awards.

Shows:
- Summary of match types
- All ambiguous matches (need human decision)
- Peer institution matches (verify these are correct)
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "federal_awards.db"

PEER_NAMES = [
    "UNIVERSITY OF NORTH TEXAS",
    "UNIVERSITY OF TEXAS AT AUSTIN",
    "TEXAS A&M UNIVERSITY",
    "UNIVERSITY OF TEXAS AT ARLINGTON",
    "UNIVERSITY OF TEXAS AT DALLAS",
    "UNIVERSITY OF TEXAS RIO GRANDE VALLEY",
    "UNIVERSITY OF TEXAS AT EL PASO",
    "UNIVERSITY OF TEXAS AT SAN ANTONIO",
    "UNIVERSITY OF HOUSTON",
    "TEXAS TECH UNIVERSITY",
    "TEXAS STATE UNIVERSITY",
    "ARIZONA STATE UNIVERSITY",
    "GEORGIA STATE UNIVERSITY",
    "UNIVERSITY OF CENTRAL FLORIDA",
    "PURDUE UNIVERSITY",
    "UNIVERSITY OF CALIFORNIA RIVERSIDE",
    "UNIVERSITY OF ILLINOIS CHICAGO",
    "UNIVERSITY OF UTAH",
    "UNIVERSITY OF SOUTH FLORIDA",
    "UNIVERSITY OF MEMPHIS",
    "TULANE UNIVERSITY",
]


def run():
    conn = sqlite3.connect(DB_PATH)

    # ── Summary ────────────────────────────────────────────────────────────
    print("=" * 60)
    print("STAGING TABLE SUMMARY")
    print("=" * 60)
    rows = conn.execute("""
        SELECT match_type, COUNT(*) as n
        FROM institutions_samgov_staging
        GROUP BY match_type ORDER BY n DESC
    """).fetchall()
    for match_type, n in rows:
        print(f"  {match_type:<25} {n:>6,}")

    # ── Peer institution check ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PEER INSTITUTION MATCHES")
    print("=" * 60)
    for peer in PEER_NAMES:
        row = conn.execute("""
            SELECT inst_name_raw, match_type, inst_uei, samgov_legal_name,
                   samgov_state, match_score
            FROM institutions_samgov_staging
            WHERE UPPER(inst_name_raw) LIKE ?
            ORDER BY match_score DESC LIMIT 1
        """, (f"%{peer}%",)).fetchone()
        if row:
            print(f"  {peer}")
            print(f"    Raw: {row[0]}")
            print(f"    Type: {row[1]}  Score: {row[5]:.2f}")
            print(f"    UEI: {row[2]}  SAM Name: {row[3]}  State: {row[4]}")
        else:
            print(f"  {peer}  → NOT FOUND IN STAGING")

    # ── Ambiguous matches (need review) ────────────────────────────────────
    ambiguous = conn.execute("""
        SELECT inst_name_raw, inst_uei, samgov_legal_name,
               samgov_state, match_score, candidates_json
        FROM institutions_samgov_staging
        WHERE match_type = 'samgov_ambiguous'
        ORDER BY match_score DESC
    """).fetchall()

    if ambiguous:
        print(f"\n{'='*60}")
        print(f"AMBIGUOUS MATCHES ({len(ambiguous)}) — REVIEW REQUIRED")
        print(f"{'='*60}")
        for raw, uei, sam_name, sam_state, score, cands_json in ambiguous:
            print(f"\n  Query:     {raw}")
            print(f"  Best pick: {uei}  {sam_name}  ({sam_state})  score={score:.2f}")
            try:
                cands = json.loads(cands_json or "[]")
                if len(cands) > 1:
                    print(f"  Other candidates:")
                    for c in cands[1:4]:
                        print(f"    {c.get('uei')}  {c.get('name')}  {c.get('state')}")
            except Exception:
                pass
    else:
        print("\nNo ambiguous matches — all clear!")

    conn.close()


if __name__ == "__main__":
    run()
