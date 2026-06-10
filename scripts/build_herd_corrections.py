"""
Build data/herd_uei_corrections.csv
Covers all institutions needing manual UEI correction:
  - Wrong name-matches (institution matched to system/foundation UEI)
  - Unmatched institutions (not found via IPEDS or name)
For each, searches the awards DB for the best candidate UEI and flags confidence.
"""
import sqlite3
import csv

DB_PATH = "data/federal_awards.db"
OUT_PATH = "data/herd_uei_corrections.csv"

# (herd_inst_id, herd_name, herd_state, herd_federal_rd_m, [search_keywords])
TO_FIX = [
    # --- Wrong name-matches ---
    ("102092", "University of Maryland",                                    "MD", 922.0,  ["UNIVERSITY OF MARYLAND COLLEGE PARK", "UNIV OF MARYLAND COLLEGE"]),
    ("008802", "The Ohio State University",                                  "OH", 774.0,  ["OHIO STATE UNIVERSITY, THE", "OHIO STATE UNIVERSITY"]),
    ("102130", "University of Nebraska, Lincoln and Medical Center",         "NE", 301.0,  ["UNIVERSITY OF NEBRASKA-LINCOLN", "UNIVERSITY OF NEBRASKA LINCOLN"]),
    ("009554", "State University of New York, University at Buffalo",        "NY", 285.0,  ["UNIVERSITY AT BUFFALO", "SUNY BUFFALO"]),
    ("022635", "The Scripps Research Institute",                             "CA", 272.0,  ["SCRIPPS RESEARCH INSTITUTE", "SCRIPPS RESEARCH"]),
    ("029001", "University of Kansas",                                       "KS", 246.0,  ["UNIVERSITY OF KANSAS", "UNIV OF KANSAS"]),
    ("102078", "Albert Einstein College of Medicine",                        "NY", 243.0,  ["ALBERT EINSTEIN COLLEGE", "EINSTEIN COLLEGE OF MEDICINE"]),
    ("009555", "State University of New York, Stony Brook University",       "NY", 186.0,  ["STONY BROOK UNIVERSITY", "STATE UNIV OF NY STONY BROOK"]),
    ("002835", "State University of New York, University at Albany",         "NY", 105.0,  ["UNIVERSITY AT ALBANY", "SUNY ALBANY"]),
    ("001369", "United States Air Force Academy",                            "CO",  52.0,  ["AIR FORCE ACADEMY", "US AIR FORCE ACADEMY"]),
    ("002840", "State University of New York, Upstate Medical University",   "NY",  38.0,  ["UPSTATE MEDICAL UNIVERSITY", "SUNY UPSTATE"]),
    ("101185", "Touro University, New York",                                 "NY",  35.0,  ["TOURO COLLEGE", "TOURO UNIVERSITY"]),
    ("002516", "University of Missouri, Columbia",                           "MO", 509.0,  ["UNIVERSITY OF MISSOURI-COLUMBIA", "UNIVERSITY OF MISSOURI COLUMBIA"]),
    ("002519", "University of Missouri, Saint Louis",                        "MO",  15.0,  ["UNIVERSITY OF MISSOURI-ST. LOUIS", "UNIVERSITY OF MISSOURI ST LOUIS"]),
    ("002836", "State University of New York, Binghamton University",        "NY", 161.0,  ["BINGHAMTON UNIVERSITY", "SUNY BINGHAMTON"]),
    # --- Unmatched ---
    ("001086", "University of Arkansas Pine Bluff",                          "AR",   4.7,  ["ARKANSAS PINE BLUFF", "PINE BLUFF"]),
    ("001813", "Indiana University-Purdue University, Indianapolis",         "IN",  41.0,  ["INDIANA UNIVERSITY-PURDUE UNIVERSITY INDIANAPOLIS", "IUPUI"]),
    ("002078", "Loyola University Maryland",                                  "MD",   0.8,  ["LOYOLA UNIVERSITY MARYLAND", "LOYOLA MARYLAND"]),
    ("002130", "Boston University",                                           "MA", 421.8,  ["TRUSTEES OF BOSTON UNIVERSITY", "BOSTON UNIVERSITY"]),
    ("002568", "University of Nevada, Reno",                                  "NV",  89.2,  ["UNIVERSITY OF NEVADA RENO", "UNIVERSITY OF NEVADA, RENO"]),
    ("002631", "Rutgers, The State University of New Jersey, Newark",         "NJ",  17.1,  ["RUTGERS UNIVERSITY NEWARK", "RUTGERS THE STATE UNIV OF NJ NEWARK"]),
    ("002687", "City University of New York, The, Brooklyn College",          "NY",   5.7,  ["CUNY BROOKLYN COLLEGE", "BROOKLYN COLLEGE"]),
    ("002690", "City University of New York, The, Queens College",            "NY",  19.0,  ["CUNY QUEENS COLLEGE", "QUEENS COLLEGE"]),
    ("002707", "Columbia University in the City of New York",                 "NY", 1076.8, ["TRUSTEES OF COLUMBIA UNIVERSITY", "COLUMBIA UNIVERSITY IN THE CITY"]),
    ("002845", "State University of New York College, Geneseo",               "NY",   1.1,  ["SUNY GENESEO", "COLLEGE AT GENESEO"]),
    ("003009", "Air Force Institute of Technology",                           "OH",  44.1,  ["AIR FORCE INST OF TECH", "AIR FORCE INSTITUTE OF TECHNOLOGY"]),
    ("003657", "The University of Texas M. D. Anderson Cancer Center",        "TX", 282.4,  ["MD ANDERSON CANCER", "ANDERSON CAN CTR", "M.D. ANDERSON"]),
    ("004063", "The City University of New York, The, Graduate Center",       "NY",   3.2,  ["CUNY GRADUATE SCH", "GRADUATE SCH AND UNIV CTR"]),
    ("004508", "University of Colorado Anschutz Medical Campus",              "CO", 498.4,  ["ANSCHUTZ MEDICAL", "UNIVERSITY OF COLORADO ANSCHUTZ"]),
    ("004741", "Rutgers, The State University of New Jersey, Camden",         "NJ",   2.8,  ["RUTGERS UNIVERSITY CAMDEN", "RUTGERS THE STATE UNIV OF NJ CAMDEN"]),
    ("004759", "City University of New York, The, York College",              "NY",   1.3,  ["CUNY YORK COLLEGE", "YORK COLLEGE"]),
    ("004766", "City University of New York, The, Baruch College",            "NY",   2.2,  ["CUNY BARUCH COLLEGE", "BARUCH COLLEGE"]),
    ("004952", "The University of Texas Medical Branch",                      "TX", 161.7,  ["UNIVERSITY OF TEXAS MEDICAL BRANCH", "UTMB"]),
    ("006964", "Rutgers, The State University of New Jersey, New Brunswick",  "NJ", 408.3,  ["RUTGERS UNIVERSITY NEW BRUNSWICK", "RUTGERS THE STATE UNIV OF NJ NEW BRUNSWICK"]),
    ("007022", "City University of New York, The, Lehman College",            "NY",   4.3,  ["CUNY LEHMAN COLLEGE", "LEHMAN COLLEGE"]),
    ("011245", "West Virginia School of Osteopathic Medicine",                "WV",   0.3,  ["WEST VIRGINIA SCHOOL OF OSTEOPATHIC", "WV OSTEOPATHIC"]),
    ("012841", "Universidad Ana G. Mendez, Gurabo",                           "PR",   1.7,  ["ANA G. MENDEZ", "ANA G MENDEZ"]),
    ("029040", "City University of New York, The, College of Staten Island",  "NY",   4.6,  ["CUNY COLLEGE OF STATEN ISLAND", "COLLEGE OF STATEN ISLAND"]),
    ("029169", "Uniformed Services University of the Health Sciences",        "MD", 482.2,  ["UNIFORMED SERVICES UNIVERSITY", "USUHS"]),
    ("100189", "Hartford International University for Religion and Peace",    "CT",   0.0,  ["HARTFORD INTERNATIONAL", "HARTFORD SEMINARY"]),
    ("100267", "University of Hawaii Maui College",                           "HI",   1.4,  ["HAWAII MAUI COLLEGE", "MAUI COLLEGE"]),
    ("100665", "Saint John Fisher University",                                "NY",   0.4,  ["SAINT JOHN FISHER", "ST. JOHN FISHER"]),
    ("100864", "Naval War College",                                           "RI",   5.9,  ["NAVAL WAR COLLEGE"]),
    ("101262", "Liberty University",                                          "VA",   0.5,  ["LIBERTY UNIVERSITY"]),
    ("101481", "National Defense University",                                 "DC",   3.5,  ["NATIONAL DEFENSE UNIVERSITY"]),
    ("101555", "Edward Via College of Osteopathic Medicine",                  "VA",   0.7,  ["EDWARD VIA COLLEGE", "VIA COLLEGE OF OSTEOPATHIC"]),
    ("101602", "Roseman University of Health Sciences",                       "NV",   0.1,  ["ROSEMAN UNIVERSITY"]),
    ("101662", "United States Army War College",                              "PA",   6.8,  ["ARMY WAR COLLEGE", "US ARMY WAR COLLEGE"]),
    ("101708", "Memorial Sloan Kettering Cancer Center",                      "NY",   0.4,  ["SLOAN KETTERING INSTITUTE", "MEMORIAL SLOAN KETTERING"]),
    ("102004", "University of North Carolina, general administration",        "NC",   0.0,  ["NORTH CAROLINA GENERAL ADMIN"]),
    ("102015", "High Tech High Graduate School of Education",                 "CA",   0.0,  ["HIGH TECH HIGH"]),
    ("102045", "State University of New York Polytechnic Institute",          "NY",   0.7,  ["SUNY POLY", "SUNY POLYTECHNIC"]),
    ("102056", "University of Texas Health Science Center at Tyler",          "TX",   8.4,  ["UT HEALTH SCIENCE CENTER AT TYLER", "UNIVERSITY OF TEXAS HLTH CTR AT TYLER"]),
    ("102060", "City University of New York, The, Advanced Science Research Center", "NY", 15.1, ["CUNY ADVANCED SCIENCE", "ADVANCED SCIENCE RESEARCH CENTER"]),
    ("102091", "City University of New York, Graduate School of Public Health and Health Policy", "NY", 16.8, ["CUNY SCHOOL OF PUBLIC HEALTH", "GRADUATE SCHOOL OF PUBLIC HEALTH"]),
    ("208828", "William and Mary",                                            "VA",  41.5,  ["COLLEGE OF WILLIAM AND MARY", "WILLIAM & MARY"]),
    ("233046", "Western Michigan University and Homer Stryker M.D. School of Medicine", "MI", 11.9, ["WESTERN MICHIGAN UNIVERSITY"]),
    ("330010", "Southern University and A&M College, Agricultural Research and Extension Center", "LA", 5.9, ["SOUTHERN UNIVERSITY AND A&M", "SOUTHERN UNIV AND A&M"]),
    ("330050", "City University of New York system office",                   "NY",   2.1,  ["CITY UNIVERSITY OF NEW YORK, THE", "CUNY SYSTEM"]),
    ("353086", "Vanderbilt University and Vanderbilt University Medical Center", "TN", 809.7, ["VANDERBILT UNIVERSITY MEDICAL", "VANDERBILT UNIVERSITY"]),
]


def build_index(conn):
    """Load (uei, name, cnt, total_m) into memory grouped by upper name."""
    rows = conn.execute(
        """SELECT UPPER(TRIM(inst_name)), inst_uei, COUNT(*) cnt,
                  ROUND(SUM(awd_amount)/1e6,1) m
           FROM awards
           WHERE inst_uei IS NOT NULL AND LENGTH(TRIM(inst_uei))=12
           GROUP BY 1, 2"""
    ).fetchall()
    index = {}  # upper_name -> list of (uei, cnt, total_m)
    for name, uei, cnt, m in rows:
        index.setdefault(name, []).append((uei, cnt, m or 0.0))
    return index


def search_best(index, keywords):
    """Return (uei, matched_name, award_cnt, total_m) using in-memory index."""
    best = ("", "", 0, 0.0)
    for kw in keywords:
        kw_up = kw.upper()
        for name, entries in index.items():
            if kw_up in name:
                for uei, cnt, m in entries:
                    if cnt > best[2]:
                        best = (uei, name, cnt, m)
    return best


def status(fed_m, awards_cnt, awards_total_m):
    if not awards_cnt:
        return "NOT_FOUND"
    if fed_m > 50 and awards_total_m < fed_m * 0.05:
        return "NEEDS_REVIEW"
    return "AUTO"


def main():
    conn = sqlite3.connect(DB_PATH)
    print("Loading awards index into memory...")
    index = build_index(conn)
    conn.close()
    print(f"  {len(index):,} distinct names loaded.")

    rows = []

    for inst_id, name, state, fed_m, keywords in TO_FIX:
        uei, awd_name, cnt, total_m = search_best(index, keywords)
        st = status(fed_m, cnt, total_m or 0)
        rows.append({
            "herd_inst_id":           inst_id,
            "herd_name":              name,
            "herd_state":             state,
            "herd_federal_rd_m":      fed_m,
            "suggested_uei":          uei,
            "suggested_uei_name":     (awd_name or "")[:70],
            "suggested_awards_cnt":   cnt,
            "suggested_awards_total_m": total_m or 0,
            "status":                 st,
            "confirmed_uei":          "",   # fill in manually if NEEDS_REVIEW / NOT_FOUND
            "notes":                  "",
        })

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    auto    = sum(1 for r in rows if r["status"] == "AUTO")
    review  = sum(1 for r in rows if r["status"] == "NEEDS_REVIEW")
    nf      = sum(1 for r in rows if r["status"] == "NOT_FOUND")

    print(f"Written: {OUT_PATH}")
    print(f"  AUTO (confident):  {auto}")
    print(f"  NEEDS_REVIEW:      {review}")
    print(f"  NOT_FOUND:         {nf}")
    print(f"  Total:             {len(rows)}")
    print()
    print("NEEDS_REVIEW:")
    for r in rows:
        if r["status"] == "NEEDS_REVIEW":
            print(f"  {r['herd_inst_id']}  ${r['herd_federal_rd_m']:.0f}M  cnt={r['suggested_awards_cnt']}  total=${r['suggested_awards_total_m']:.0f}M  {r['herd_name']}")
    print()
    print("NOT_FOUND:")
    for r in rows:
        if r["status"] == "NOT_FOUND":
            print(f"  {r['herd_inst_id']}  ${r['herd_federal_rd_m']:.0f}M  {r['herd_name']}")


if __name__ == "__main__":
    main()
