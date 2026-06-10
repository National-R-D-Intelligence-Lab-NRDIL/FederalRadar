"""
Pre-flight: classify unmatched NSF/NIH names into universities vs. other entities.
We only need SAM.gov lookups for universities/research institutions.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "federal_awards.db"

UNIVERSITY_KEYWORDS = [
    'UNIVERSITY', 'COLLEGE', 'INSTITUTE OF TECHNOLOGY', 'POLYTECHNIC',
    'SCHOOL OF', 'ACADEMY', 'SEMINARY', 'CONSERVATORY',
]

def looks_like_university(name: str) -> bool:
    n = name.upper()
    return any(kw in n for kw in UNIVERSITY_KEYWORDS)

conn = sqlite3.connect(DB_PATH)

existing = {
    r[0].upper()
    for r in conn.execute("SELECT canonical_name FROM institutions WHERE canonical_name IS NOT NULL")
}

nsf_nih_names = [
    r[0] for r in conn.execute("""
        SELECT DISTINCT inst_name FROM awards
        WHERE source IN ('nsf', 'nih')
        AND inst_name IS NOT NULL AND inst_name != ''
    """)
]

unmatched = [n for n in nsf_nih_names if n.upper() not in existing]

uni_unmatched     = [n for n in unmatched if looks_like_university(n)]
non_uni_unmatched = [n for n in unmatched if not looks_like_university(n)]

print(f"Total unmatched:                {len(unmatched):,}")
print(f"  University-like (need lookup): {len(uni_unmatched):,}")
print(f"  Small biz / other (skip):      {len(non_uni_unmatched):,}")
print(f"\nSAM.gov calls needed: {len(uni_unmatched):,}")

# How many NSF/NIH records do the unmatched universities cover?
uni_upper = {n.upper() for n in uni_unmatched}
rows = conn.execute("""
    SELECT COUNT(*), source FROM awards
    WHERE source IN ('nsf','nih')
    AND inst_name IS NOT NULL
    GROUP BY source
""").fetchall()
for n, src in rows:
    print(f"  Total {src} records: {n:,}")

print(f"\nSample unmatched universities:")
for n in sorted(uni_unmatched)[:30]:
    print(f"  {n}")

conn.close()
