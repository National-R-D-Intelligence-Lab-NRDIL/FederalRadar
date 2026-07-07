"""
Build HERD-IPEDS → Awards DB UEI crosswalk.

Produces: data/herd_ipeds_crosswalk.csv

One row per IPEDS research institution (Carnegie C18BASIC 15–20).
Maps each institution's IPEDS identity to the correct UEI in the
federal awards database (which may differ due to SAM.gov entity
registration vs. IPEDS registration).

Match priority:
  1. direct        — IPEDS primary UEI matches awards DB exactly
  2. secondary_uei — One of the pipe-separated IPEDS UEIs matches
  3. case_fix      — IPEDS UEI matches after UPPER() normalization
  4. manual        — Hardcoded override (known entity filing differences)
  5. name_match    — Keyword search of awards DB (≥2 keyword hits)
  6. no_awards     — No match found in awards DB
"""

import csv
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(os.environ.get("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "federal_awards.db")))
IPEDS = Path(__file__).parent.parent / "data" / "ipeds" / "HD2023.csv"
OUT = Path(__file__).parent.parent / "data" / "herd_ipeds_crosswalk.csv"

# Carnegie C18BASIC codes to include (doctoral + masters = HERD-eligible).
# 25 = Special Focus Four-Year: Medical Schools & Health Science Centers.
# Included so freestanding HSCs (e.g. UNT Health Science Center, UT Southwestern)
# are independently selectable — never merged into a parent university's record.
RESEARCH_CODES = {"15", "16", "17", "18", "19", "20", "25"}

# Keyed by (INSTNM.strip(), STABBR) -> (awards_uei_or_None, reason)
# None = confirmed not in awards DB, don't attempt name_match
MANUAL_OVERRIDES = {
    # --- UEI is correct in awards DB, IPEDS has a typo ---
    ("University of North Texas", "TX"):
        ("G47WN1XZNWX9", "IPEDS UEI trailing char typo (g→9)"),
    ("Texas Southern University", "TX"):
        ("HYYJJ5ZP7CR9", "IPEDS UEI single-char typo pos 1 (H→Y)"),
    ("Eastern Washington University", "WA"):
        ("QL3XATN9H6L1", "IPEDS UEI char swap (986→H6L)"),

    # --- Institution files under a different SAM.gov entity ---
    ("University of Utah", "UT"):
        ("LL8GLEVH6MG3", "Different SAM.gov entity; awards filed as 'University of Utah'"),
    ("University of Maryland-College Park", "MD"):
        ("NPU8ULVAAS23", "Files as UNIVERSITY OF MARYLAND, COLLEGE PARK"),
    ("George Washington University", "DC"):
        ("ECR5E2LU5BL6", "Different SAM.gov entity"),
    ("Ball State University", "IN"):
        ("KDP6QKY6QLM1", "Different SAM.gov entity"),
    ("Indiana University-Indianapolis", "IN"):
        ("SHHBRBAPSM35", "Campus files as INDIANA UNIVERSITY INDIANAPOLIS"),
    ("Indiana University-Bloomington", "IN"):
        ("YH86RTW2YVJ4", "Files under Indiana University system UEI"),
    ("Indiana University-South Bend", "IN"):
        ("YH86RTW2YVJ4", "Rolls up to Indiana University system UEI"),
    ("Indiana University-Northwest", "IN"):
        ("YH86RTW2YVJ4", "Rolls up to Indiana University system UEI"),
    ("Indiana University-Southeast", "IN"):
        ("YH86RTW2YVJ4", "Rolls up to Indiana University system UEI"),
    ("Indiana University-East", "IN"):
        ("YH86RTW2YVJ4", "Rolls up to Indiana University system UEI"),
    ("Bowie State University", "MD"):
        ("WMEEHCAPGR65", "Different SAM.gov entity"),
    ("University at Albany", "NY"):
        ("NHH3T1Z96H29", "Files as SUNY AT ALBANY"),
    ("Stony Brook University", "NY"):
        ("M746VC6XMNH9", "Files as STATE UNIVERSITY NEW YORK STONY BROOK"),
    ("CUNY Brooklyn College", "NY"):
        ("XNAKYW3FTSE1", "Different SAM.gov entity"),
    ("College of Staten Island CUNY", "NY"):
        ("L63BKBLD2LH4", "Different SAM.gov entity"),
    ("CUNY Queens College", "NY"):
        ("EJABWGUJM228", "Different SAM.gov entity"),
    ("SUNY College at Geneseo", "NY"):
        ("RCHLJW4S5BC4", "Different SAM.gov entity"),
    ("SUNY Old Westbury", "NY"):
        ("JJ2FXBDGWMG5", "Different SAM.gov entity"),
    ("University of New Hampshire-Main Campus", "NH"):
        ("GBNGC495XA67", "Files under University System of New Hampshire"),
    ("University of New Hampshire College of Professional Studies Online", "NH"):
        ("GBNGC495XA67", "Same system UEI as UNH main campus"),
    ("Fairleigh Dickinson University-Florham Campus", "NJ"):
        ("KYWWQMMM1PZ4", "Files as FAIRLEIGH DICKINSON UNIVERSITY"),
    ("Montclair State University", "NJ"):
        ("CM4TTRKFCLF9", "Different SAM.gov entity"),
    ("Fashion Institute of Technology", "NY"):
        ("Z5LQE3L4RKH8", "Different SAM.gov entity"),
    ("Saint Cloud State University", "MN"):
        ("QJ1NBA1JTPA3", "Files as ST. CLOUD STATE UNIVERSITY"),
    ("Coastal Carolina University", "SC"):
        ("D9KPSNLHD9J5", "Different SAM.gov entity"),
    ("The University of Tennessee-Chattanooga", "TN"):
        ("JNZFHMGJN7M3", "Files as UNIVERSITY OF TENNESSEE CHATTANOOGA"),
    ("University of North Texas at Dallas", "TX"):
        ("GMKZCPHGJUX6", "Different SAM.gov entity"),
    # Double-space in IPEDS name — handle both variants
    ("Clayton  State University", "GA"):
        ("JDPQA8949685", "Non-standard IPEDS UEI (EIN format); matched by name"),
    ("Clayton State University", "GA"):
        ("JDPQA8949685", "Non-standard IPEDS UEI (EIN format); matched by name"),
    ("Andrews University", "MI"):
        ("QXJLKBKFT4H7", "Different SAM.gov entity"),
    ("Kennesaw State University", "GA"):
        ("G8DZHNRKWTN3", "Awards filed through Kennesaw State Research & Service Foundation"),

    # --- Single-keyword names: name_match misses these (need explicit override) ---
    ("University of Nevada-Reno", "NV"):
        ("WLDGTNCFFJZ3", "Files as Board of Regents, NSHE, obo University of Nevada, Reno"),
    ("Stevens Institute of Technology", "NJ"):
        ("JJ6CN5Y5A2R5", "Different SAM.gov entity"),
    ("Delaware State University", "DE"):
        ("RZZ8BMQ47KX3", "Different SAM.gov entity"),
    ("San Francisco State University", "CA"):
        ("F4SLJ5WF59F6", "Different SAM.gov entity"),
    ("Hampton University", "VA"):
        ("KSJKE3KVNBB4", "Different SAM.gov entity"),
    ("Weber State University", "UT"):
        ("ZAVDUCLBZG77", "Different SAM.gov entity"),
    ("University of Scranton", "PA"):
        ("WV3XJPNFUL58", "Different SAM.gov entity"),
    ("Grambling State University", "LA"):
        ("GAWTFKJ8ZRC5", "Different SAM.gov entity"),
    ("University of New Haven", "CT"):
        ("FZBDVM1MBTN9", "Different SAM.gov entity"),
    ("Austin Peay State University", "TN"):
        ("RWKCVTBEDCX7", "Different SAM.gov entity"),
    ("New Jersey City University", "NJ"):
        ("FU7YL2GAWHY3", "Different SAM.gov entity"),
    ("Fort Hays State University", "KS"):
        ("DVSMS2BMAK51", "Different SAM.gov entity"),
    ("Bentley University", "MA"):
        ("N6DAMDJXFJ65", "Different SAM.gov entity"),

    # --- Confirmed not in awards DB (set to None to skip name_match) ---
    ("Concordia University Texas", "TX"):
        (None, "Small Lutheran school; name_match false positive via keyword TEXAS"),
    ("Texas A&M University-Texarkana", "TX"):
        (None, "Small A&M campus with no IPEDS UEI; name_match false positive via keyword TEXAS"),
    ("CUNY Lehman College", "NY"):
        (None, "Not found in awards DB; may file through CUNY Research Foundation"),
    ("SUNY Polytechnic Institute", "NY"):
        (None, "Not clearly identified in awards DB"),
    ("University of Baltimore", "MD"):
        (None, "Distinct from U of Maryland Baltimore; not found in awards DB"),
}

STOPWORDS = {
    "UNIVERSITY", "COLLEGE", "INSTITUTE", "TECHNOLOGY", "THE", "AND",
    "FOR", "SCIENCES", "SCIENCE", "ARTS", "SCHOOL", "STATE", "SYSTEM",
    "NATIONAL", "CENTER", "RESEARCH",
}


def main():
    # --- Load IPEDS ---
    # NCES files are latin-1 encoded with a UTF-8 BOM prepended (Windows export artifact).
    # Strip the BOM from the first field name so UNITID is accessible as 'UNITID'.
    with open(IPEDS, "r", encoding="latin-1") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and reader.fieldnames[0].startswith("\xef\xbb\xbf"):
            reader.fieldnames[0] = reader.fieldnames[0][3:]
        elif reader.fieldnames and reader.fieldnames[0].startswith("\ufeff"):
            reader.fieldnames[0] = reader.fieldnames[0][1:]
        ipeds_rows = list(reader)
    research_insts = [
        r for r in ipeds_rows
        if r.get("C18BASIC", "").strip() in RESEARCH_CODES
    ]
    print(f"IPEDS research institutions (C18BASIC 15–20): {len(research_insts)}")

    # --- Load awards DB ---
    conn = sqlite3.connect(DB)

    # Build UEI index: uei -> (canonical_name, count, total_m)
    # Take row with highest award count per UEI
    awards_index = {}
    for uei, name, cnt, total_m in conn.execute("""
        SELECT inst_uei,
               COALESCE(inst_canonical_name, ''),
               COUNT(*),
               COALESCE(SUM(awd_amount) / 1e6, 0.0)
        FROM awards
        WHERE inst_uei IS NOT NULL
        GROUP BY inst_uei
        ORDER BY COUNT(*) DESC
    """):
        if uei not in awards_index:
            awards_index[uei] = (name, cnt, round(total_m, 1))

    awards_ueis_upper = {u.upper(): u for u in awards_index}

    # Build keyword → [(uei, name, cnt, total_m)] index for name_match
    word_index = defaultdict(list)
    for uei, (name, cnt, total_m) in awards_index.items():
        for word in name.upper().split():
            if len(word) > 4 and word not in STOPWORDS:
                word_index[word].append((uei, name, cnt, total_m))

    def name_search(instnm):
        """Return best (uei, name, cnt, total_m) with ≥2 keyword hits, or None."""
        words = [
            w.upper()
            for w in re.sub(r"[^A-Za-z0-9 ]", " ", instnm).split()
            if w.upper() not in STOPWORDS and len(w) > 3
        ]
        candidates = defaultdict(lambda: [0, 0, 0.0, ""])  # hits, cnt, total_m, name
        for word in words[:6]:
            for uei, name, cnt, total_m in word_index.get(word, []):
                candidates[uei][0] += 1
                if cnt > candidates[uei][1]:
                    candidates[uei][1] = cnt
                    candidates[uei][2] = total_m
                    candidates[uei][3] = name
        ranked = sorted(candidates.items(), key=lambda x: (-x[1][0], -x[1][1]))
        if ranked and ranked[0][1][0] >= 2:
            uei, info = ranked[0]
            return uei, info[3], info[1], info[2]
        return None

    # --- Process each institution ---
    results = []
    stats = defaultdict(int)

    for r in research_insts:
        unitid = r.get("UNITID", "").strip()
        instnm = r["INSTNM"].strip()
        stabbr = r["STABBR"].strip()
        c18 = r["C18BASIC"].strip()
        ipeds_uei_raw = r.get("UEIS", "").strip()
        ipeds_ueis = [u.strip() for u in ipeds_uei_raw.split("|") if u.strip()]

        awards_uei = None
        awards_name = ""
        awards_count = 0
        awards_total_m = 0.0
        match_type = "no_awards"
        note = ""
        manually_excluded = False

        # 1. Direct match: primary IPEDS UEI in awards DB
        if ipeds_ueis and ipeds_ueis[0] in awards_index:
            awards_uei = ipeds_ueis[0]
            match_type = "direct"

        # 2. Secondary UEI (pipe-separated alternatives in IPEDS)
        if not awards_uei and len(ipeds_ueis) > 1:
            for u in ipeds_ueis[1:]:
                if u in awards_index:
                    awards_uei = u
                    match_type = "secondary_uei"
                    break

        # 3. Case-normalized UEI (IPEDS sometimes stores lowercase or mixed case)
        if not awards_uei:
            for u in ipeds_ueis:
                u_upper = u.upper()
                if u_upper in awards_ueis_upper:
                    awards_uei = awards_ueis_upper[u_upper]
                    match_type = "case_fix"
                    note = f"IPEDS stored as '{u}', normalized to '{awards_uei}'"
                    break

        # 4. Manual override (known entity filing differences, IPEDS typos, or confirmed no-match)
        override_key = (instnm, stabbr)
        if override_key in MANUAL_OVERRIDES:
            override_uei, override_note = MANUAL_OVERRIDES[override_key]
            if override_uei is not None:
                awards_uei = override_uei
                match_type = "manual"
                note = override_note
            else:
                # Explicitly excluded — do NOT fall through to name_match
                awards_uei = None
                match_type = "no_awards"
                note = override_note
                manually_excluded = True

        # 5. Name keyword search (fallback only — skipped for manual exclusions)
        if not awards_uei and not manually_excluded:
            result = name_search(instnm)
            if result:
                awards_uei, nm, cnt, tm = result
                match_type = "name_match"
                note = f"Keyword match → '{nm}'"

        # Populate award stats from index
        if awards_uei and awards_uei in awards_index:
            awards_name, awards_count, awards_total_m = awards_index[awards_uei]

        stats[match_type] += 1
        results.append({
            "unitid": unitid,
            "ipeds_name": instnm,
            "state": stabbr,
            "carnegie": c18,
            "ipeds_uei": ipeds_uei_raw,
            "awards_uei": awards_uei or "",
            "awards_name": awards_name,
            "awards_count": awards_count,
            "awards_total_m": awards_total_m,
            "match_type": match_type,
            "note": note,
        })

    conn.close()

    # --- Write CSV ---
    fieldnames = [
        "unitid", "ipeds_name", "state", "carnegie", "ipeds_uei",
        "awards_uei", "awards_name", "awards_count", "awards_total_m",
        "match_type", "note",
    ]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nWrote {len(results):,} rows to {OUT}")

    print("\nMatch type summary:")
    for mtype, cnt in sorted(stats.items(), key=lambda x: -x[1]):
        pct = cnt / len(results) * 100
        print(f"  {mtype:20s}: {cnt:4d}  ({pct:.1f}%)")

    matched = sum(1 for r in results if r["awards_uei"])
    print(f"\nTotal matched: {matched}/{len(results)} = {matched / len(results) * 100:.1f}%")

    # Show no_awards institutions for review
    unmatched = [r for r in results if not r["awards_uei"]]
    if unmatched:
        print(f"\nUnmatched institutions ({len(unmatched)}):")
        for r in sorted(unmatched, key=lambda x: (x["carnegie"], x["ipeds_name"])):
            print(f"  [C{r['carnegie']}] {r['ipeds_name']} ({r['state']})  {r['note']}")

    # Sanity check: verify all manual override UEIs exist in awards DB
    print("\nManual override verification:")
    conn2 = sqlite3.connect(DB)
    all_ok = True
    for (name, state), (uei, _) in MANUAL_OVERRIDES.items():
        if uei is None:
            continue
        exists = conn2.execute(
            "SELECT COUNT(*) FROM awards WHERE inst_uei = ?", (uei,)
        ).fetchone()[0]
        if exists == 0:
            print(f"  WARNING: override UEI {uei} for '{name}' ({state}) not in awards DB!")
            all_ok = False
    if all_ok:
        print("  All override UEIs confirmed in awards DB.")
    conn2.close()


if __name__ == "__main__":
    main()
