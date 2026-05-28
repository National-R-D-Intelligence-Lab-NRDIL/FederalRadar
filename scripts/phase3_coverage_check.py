"""
Quick coverage check: of all distinct NIH/NSF universities,
how many already have a UEI via cross-source mapping?
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "federal_awards.db"

KEYWORDS = ['UNIVERSITY', 'COLLEGE', 'INSTITUTE OF TECHNOLOGY',
            'POLYTECHNIC', 'SCHOOL OF']

def is_uni(name): return any(k in name.upper() for k in KEYWORDS)

conn = sqlite3.connect(DB_PATH)

# All name→UEI mappings already in DB (NSF + USASpending)
name_to_uei = {}
for upper_name, uei in conn.execute("""
    SELECT UPPER(inst_name), inst_uei FROM awards
    WHERE source != 'nih'
    AND inst_uei IS NOT NULL AND inst_uei != ''
    AND inst_name IS NOT NULL
"""):
    name_to_uei[upper_name] = uei

print(f"Known name->UEI mappings (NSF + USASpending): {len(name_to_uei):,}")

# Distinct NIH institution names
nih_names = [r[0] for r in conn.execute("""
    SELECT DISTINCT inst_name FROM awards
    WHERE source = 'nih' AND inst_name IS NOT NULL AND inst_name != ''
""")]

unis     = [n for n in nih_names if is_uni(n)]
non_unis = [n for n in nih_names if not is_uni(n)]

matched   = [n for n in unis if n.upper() in name_to_uei]
unmatched = [n for n in unis if n.upper() not in name_to_uei]

print(f"\nDistinct NIH institution names: {len(nih_names):,}")
print(f"  University-like:  {len(unis):,}")
print(f"  Small biz/other:  {len(non_unis):,}")
print(f"\nOf the {len(unis):,} universities:")
print(f"  Already have UEI (cross-map): {len(matched):,}  ({len(matched)/len(unis)*100:.1f}%)")
print(f"  Missing UEI (need API):       {len(unmatched):,}  ({len(unmatched)/len(unis)*100:.1f}%)")

# What % of NIH RECORDS does the matched set cover?
matched_upper = {n.upper() for n in matched}
covered_records = sum(1 for r in conn.execute(
    "SELECT inst_name FROM awards WHERE source='nih' AND inst_name IS NOT NULL"
) if r[0].upper() in matched_upper)
total_nih = conn.execute("SELECT COUNT(*) FROM awards WHERE source='nih'").fetchone()[0]
print(f"\nRecord-level coverage from cross-map alone:")
print(f"  {covered_records:,} / {total_nih:,} NIH records ({covered_records/total_nih*100:.1f}%)")

# Sample of unmatched universities (NSF-only or obscure)
print(f"\nSample unmatched universities (first 30):")
for n in sorted(unmatched)[:30]:
    print(f"  {n}")

conn.close()
