"""
queries.py
All database queries for the Federal Radar Streamlit app.
All results are cached for 1 hour to keep the UI fast.
"""

import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(os.environ.get("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "federal_awards.db")))

MY_INSTITUTION = "University of North Texas"

# Full names for NSF directorate and division abbreviations (from raw_json)
NSF_DIR_NAMES = {
    "BIO":  "Biological Sciences",
    "CSE":  "Computer & Information Science & Engineering",
    "EDU":  "STEM Education",
    "ENG":  "Engineering",
    "GEO":  "Geosciences",
    "MPS":  "Mathematical & Physical Sciences",
    "SBE":  "Social, Behavioral & Economic Sciences",
    "TIP":  "Technology, Innovation & Partnerships",
    "O/D":  "Office of the Director",
    "BFA":  "Budget, Finance & Award Management",
    "IRM":  "Information & Resource Management",
    "NCO":  "National Coordination Office",
    "NNCO": "National Nanotechnology Coordinating Office",
    "OCIO": "Office of the Chief Information Officer",
}

NSF_DIV_NAMES = {
    "AGS":  "Atmospheric & Geospace Sciences",
    "AST":  "Astronomical Sciences",
    "BCS":  "Behavioral & Cognitive Sciences",
    "CBET": "Chemical, Bioengineering, Environmental & Transport Systems",
    "CCF":  "Computing & Communication Foundations",
    "CHE":  "Chemistry",
    "CMMI": "Civil, Mechanical & Manufacturing Innovation",
    "CNS":  "Computer & Network Systems",
    "DBI":  "Biological Infrastructure",
    "DEB":  "Environmental Biology",
    "DGE":  "Graduate Education",
    "DMR":  "Materials Research",
    "DMS":  "Mathematical Sciences",
    "DRL":  "Research on Learning",
    "DUE":  "Undergraduate Education",
    "EAR":  "Earth Sciences",
    "ECCS": "Electrical, Communications & Cyber Systems",
    "EEC":  "Engineering Education & Centers",
    "EES":  "Equity for Excellence in STEM",
    "EF":   "Emerging Frontiers",
    "IIS":  "Information & Intelligent Systems",
    "IOS":  "Integrative Organismal Systems",
    "MCB":  "Molecular & Cellular Biosciences",
    "OCE":  "Ocean Sciences",
    "OPP":  "Polar Programs",
    "PHY":  "Physics",
    "SES":  "Social & Economic Sciences",
    "SMA":  "Science of Science & Innovation Policy",
}

PEER_SHORT = {
    "Texas A&M University":           "A&M",
    "UT Austin":                       "UT Austin",
    "UT Arlington":                    "UTA",
    "UT Dallas":                       "UTD",
    "UTSA":                            "UTSA",
    "UTEP":                            "UTEP",
    "UTRGV":                           "UTRGV",
    "Texas State University":          "TX State",
    "Texas Tech University":           "TX Tech",
    "University of Houston":           "Houston",
    "Arizona State University":        "ASU",
    "Purdue University":               "Purdue",
    "Georgia State University":        "GA State",
    "University of South Florida":     "USF",
    "UCF":                             "UCF",
    "University of Utah":              "Utah",
    "University of Memphis":           "Memphis",
    "University of Illinois Chicago":  "UIC",
    "Tulane University":               "Tulane",
    "UC Riverside":                    "UCR",
}


# ED (Dept of Education) CFDA codes that are non-research.
# Excluded: HEERF/CARES Act, formula grants (TRIO, Impact Aid, Title III,
# Indian Ed, Rural Ed, Adult Ed).  Only IES research, FIPSE, EIR, etc. remain.
ED_NON_RESEARCH_CFDAS = (
    # HEERF / CARES Act / COVID relief
    "84.425", "84.403", "84.405", "84.407", "84.414", "84.415",
    "84.416", "84.418", "84.421", "84.422", "84.424", "84.428",
    "84.396",
    # Formula / student aid / institutional aid
    "84.041",  # Impact Aid
    "84.031",  # Title III (Strengthening Institutions)
    "84.042",  # TRIO Student Support Services
    "84.044",  # TRIO Talent Search
    "84.047",  # TRIO Upward Bound
    "84.060",  # Indian Education
    "84.358",  # Rural Education
    "84.002",  # Adult Education
    "84.007",  # Federal Supplemental Ed Opportunity Grants
    "84.033",  # Federal Work-Study
    "84.063",  # Federal Pell Grant
    "84.268",  # Federal Direct Loans
    "84.004",  # Civil Rights Training
    "84.379",  # Teacher Education Assistance
    "84.334",  # Gaining Early Awareness (GEAR UP)
    "84.165",  # Magnet Schools
    "84.374",  # Teacher & School Leader Incentive
    "84.365",  # English Language Acquisition
    "84.066",  # TRIO Educational Opportunity Centers
    "84.382",  # Strengthening Institutions (STEM)
    "84.048",  # Career & Technical Education
    "84.015",  # National Resource Centers
)

# Human-readable note for UI display
ED_EXCLUSION_NOTE = (
    "ED excludes HEERF/CARES Act and formula grants "
    "(TRIO, Impact Aid, Title III) — research awards only."
)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA cache_size = -65536;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA mmap_size = 268435456;")  # 256MB mmap
    return conn


# ---------------------------------------------------------------------------
# Filters — populate sidebar dropdowns
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_agencies() -> list[str]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source FROM awards ORDER BY source"
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=3600)
def get_nsf_directorates() -> list[str]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT dir_abbr FROM awards
               WHERE source = 'nsf' AND dir_abbr IS NOT NULL
               ORDER BY dir_abbr"""
        ).fetchall()
    return [r[0] for r in rows]


# keep old name as alias so nothing else breaks
get_nsf_divisions = get_nsf_directorates


@st.cache_data(ttl=3600)
def get_nsf_subdiv(directorate: str) -> list[str]:
    """Returns division abbreviations (div_abbr) within a directorate."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT div_abbr FROM awards
               WHERE source = 'nsf' AND dir_abbr = ?
               AND div_abbr IS NOT NULL
               ORDER BY div_abbr""",
            (directorate,),
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=3600)
def get_nsf_programs(directorate: str, division: str | None = None) -> list[str]:
    if division:
        with _conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT pgm_ele_name FROM awards
                   WHERE source = 'nsf' AND dir_abbr = ? AND div_abbr = ?
                   AND pgm_ele_name IS NOT NULL
                   ORDER BY pgm_ele_name""",
                (directorate, division),
            ).fetchall()
    else:
        with _conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT pgm_ele_name FROM awards
                   WHERE source = 'nsf' AND dir_abbr = ?
                   AND pgm_ele_name IS NOT NULL
                   ORDER BY pgm_ele_name""",
                (directorate,),
            ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=3600)
def get_nih_institutes() -> list[str]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT nih_institute FROM awards
               WHERE source = 'nih' AND nih_institute IS NOT NULL
               ORDER BY nih_institute"""
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=3600)
def get_nih_activity_codes(institute: str | None = None) -> list[str]:
    with _conn() as conn:
        if institute:
            rows = conn.execute(
                """SELECT DISTINCT activity_code FROM awards
                   WHERE source = 'nih' AND nih_institute = ?
                   AND activity_code IS NOT NULL ORDER BY activity_code""",
                (institute,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT activity_code FROM awards
                   WHERE source = 'nih' AND activity_code IS NOT NULL
                   ORDER BY activity_code"""
            ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Institution picker — HERD/IPEDS institution list
# ---------------------------------------------------------------------------

CARNEGIE_LABELS = {
    "15": "R1 — Doctoral: Very High Research",
    "16": "R2 — Doctoral: High Research",
    "17": "D/PU — Doctoral/Professional",
    "18": "M1 — Master's: Larger Programs",
    "19": "M2 — Master's: Medium Programs",
    "20": "M3 — Master's: Small Programs",
}

CARNEGIE_SHORT = {
    "15": "R1", "16": "R2", "17": "D/PU",
    "18": "M1", "19": "M2", "20": "M3",
}


@st.cache_data(ttl=3600)
def get_herd_institutions(
    state: str | None = None,
    carnegie_codes: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """
    All HERD-matched institutions for the institution picker dropdown.

    Returns DataFrame with columns:
        unitid, ipeds_name, state, carnegie, carnegie_label,
        awards_uei, awards_count, awards_total_m

    Only includes institutions with a matched awards_uei (95.6% of the
    1,053 IPEDS research institutions). Sorted alphabetically by name.

    Args:
        state: two-letter state abbreviation to filter (None = all states)
        carnegie_codes: tuple of C18BASIC codes to include, e.g. ('15','16')
                        None = all codes (15–20)
    """
    clauses = ["awards_uei IS NOT NULL"]
    params: list = []

    if state:
        clauses.append("state = ?")
        params.append(state)

    if carnegie_codes:
        placeholders = ",".join("?" * len(carnegie_codes))
        clauses.append(f"carnegie IN ({placeholders})")
        params.extend(carnegie_codes)

    sql = f"""
        SELECT unitid, ipeds_name, state, carnegie,
               awards_uei, awards_name, awards_count, awards_total_m
        FROM herd_institutions
        WHERE {" AND ".join(clauses)}
        ORDER BY ipeds_name
    """
    with _conn() as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    df["carnegie_label"] = df["carnegie"].map(CARNEGIE_SHORT).fillna(df["carnegie"])
    return df


@st.cache_data(ttl=3600)
def get_herd_states() -> list[str]:
    """Sorted list of state abbreviations that have matched HERD institutions."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT state FROM herd_institutions
               WHERE awards_uei IS NOT NULL AND state IS NOT NULL
               ORDER BY state"""
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=3600)
def get_institution_summary(awards_uei: str) -> dict:
    """
    Key stats for one institution — used to populate a summary card
    when the user selects an institution.

    Returns dict with: ipeds_name, state, carnegie_label, awards_uei,
    total_awards, total_funding_m, first_fy, last_fy, top_agency
    """
    with _conn() as conn:
        # Basic identity from herd_institutions
        meta = conn.execute(
            """SELECT ipeds_name, state, carnegie
               FROM herd_institutions WHERE awards_uei = ?""",
            (awards_uei,),
        ).fetchone()

        if not meta:
            return {}

        ipeds_name, state, carnegie = meta

        # Award stats from the awards table
        stats = conn.execute(
            """SELECT COUNT(*), ROUND(SUM(awd_amount)/1e6, 1),
                      MIN(fiscal_year), MAX(fiscal_year)
               FROM awards WHERE inst_uei = ?""",
            (awards_uei,),
        ).fetchone()

        top_agency = conn.execute(
            """SELECT source, COUNT(*) as n
               FROM awards WHERE inst_uei = ?
               GROUP BY source ORDER BY n DESC LIMIT 1""",
            (awards_uei,),
        ).fetchone()

    return {
        "ipeds_name":     ipeds_name,
        "state":          state,
        "carnegie_label": CARNEGIE_LABELS.get(carnegie, carnegie),
        "awards_uei":     awards_uei,
        "total_awards":   stats[0] or 0,
        "total_funding_m": stats[1] or 0.0,
        "first_fy":       stats[2],
        "last_fy":        stats[3],
        "top_agency":     top_agency[0] if top_agency else None,
    }


@st.cache_data(ttl=3600)
def get_cfda_programs(agency: str) -> list[tuple[str, str]]:
    """Returns (opportunity_number, cfda_title) for a USASpending agency."""
    ed_clause, ed_params = _ed_exclusion_clause()
    with _conn() as conn:
        rows = conn.execute(
            f"""SELECT DISTINCT opportunity_number,
                      COALESCE(cfda_title, opportunity_number)
               FROM awards
               WHERE source = ? AND opportunity_number IS NOT NULL
                 AND {ed_clause}
               ORDER BY opportunity_number""",
            (agency, *ed_params),
        ).fetchall()
    return rows


# ---------------------------------------------------------------------------
# Program Explorer queries
# ---------------------------------------------------------------------------

def _ed_exclusion_clause(alias: str = "") -> tuple[str, list]:
    """Return (SQL fragment, params) to exclude non-research ED CFDAs.

    If *alias* is given (e.g. 'a'), columns are prefixed as a.source, etc.
    """
    prefix = f"{alias}." if alias else ""
    ph = ",".join("?" * len(ED_NON_RESEARCH_CFDAS))
    clause = (
        f"NOT ({prefix}source = 'ed' AND {prefix}opportunity_number IN ({ph}))"
    )
    return clause, list(ED_NON_RESEARCH_CFDAS)


def _build_filter(source, division=None, subdiv=None, program=None,
                  institute=None, activity_code=None, cfda=None):
    """Return (WHERE clause, params) for the given filter combination."""
    clauses = ["source = ?"]
    params = [source]
    # Exclude non-research ED programs automatically
    if source == "ed":
        ed_clause, ed_params = _ed_exclusion_clause()
        clauses.append(ed_clause)
        params.extend(ed_params)
    if source == "nsf":
        if division:
            clauses.append("dir_abbr = ?")
            params.append(division)
        if subdiv:
            clauses.append("div_abbr = ?")
            params.append(subdiv)
        if program:
            clauses.append("pgm_ele_name = ?")
            params.append(program)
    elif source == "nih":
        if institute:
            clauses.append("nih_institute = ?")
            params.append(institute)
        if activity_code:
            clauses.append("activity_code = ?")
            params.append(activity_code)
    else:
        if cfda:
            clauses.append("opportunity_number = ?")
            params.append(cfda)
    return " AND ".join(clauses), params


@st.cache_data(ttl=3600)
def get_program_stats(source, division=None, subdiv=None, program=None,
                      institute=None, activity_code=None, cfda=None) -> dict:
    where, params = _build_filter(source, division, subdiv, program, institute,
                                  activity_code, cfda)
    with _conn() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) as awards,
                       COALESCE(SUM(awd_amount), 0) as total_funding,
                       COALESCE(AVG(awd_amount), 0) as avg_award,
                       COUNT(DISTINCT COALESCE(inst_uei, inst_name)) as institutions
                FROM awards WHERE {where}""",
            params,
        ).fetchone()
    return {
        "awards": row[0],
        "total_funding": row[1],
        "avg_award": row[2],
        "institutions": row[3],
    }


@st.cache_data(ttl=3600)
def get_top_institutions(source, division=None, subdiv=None, program=None,
                         institute=None, activity_code=None,
                         cfda=None, limit=25) -> pd.DataFrame:
    where, params = _build_filter(source, division, subdiv, program, institute,
                                  activity_code, cfda)
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT COALESCE(inst_canonical_name, inst_name) as inst_name,
                       inst_state_code,
                       COUNT(*) as awards,
                       ROUND(SUM(awd_amount) / 1e6, 2) as total_m,
                       ROUND(AVG(awd_amount) / 1e6, 3) as avg_m
                FROM awards WHERE {where}
                GROUP BY COALESCE(inst_canonical_name, inst_name)
                ORDER BY total_m DESC
                LIMIT {limit}""",
            conn,
            params=params,
        )
    df.index = range(1, len(df) + 1)
    df.columns = ["Institution", "State", "Awards", "Total ($M)", "Avg ($M)"]
    return df


@st.cache_data(ttl=3600)
def get_trend(source, division=None, subdiv=None, program=None,
              institute=None, activity_code=None, cfda=None) -> pd.DataFrame:
    where, params = _build_filter(source, division, subdiv, program, institute,
                                  activity_code, cfda)
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT fiscal_year,
                       COUNT(*) as awards,
                       ROUND(SUM(awd_amount) / 1e6, 2) as total_m
                FROM awards WHERE {where} AND fiscal_year IS NOT NULL
                GROUP BY fiscal_year ORDER BY fiscal_year""",
            conn,
            params=params,
        )
    return df


@st.cache_data(ttl=3600)
def get_state_distribution(source, division=None, subdiv=None, program=None,
                           institute=None, activity_code=None,
                           cfda=None) -> pd.DataFrame:
    where, params = _build_filter(source, division, subdiv, program, institute,
                                  activity_code, cfda)
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT inst_state_code as state,
                       COUNT(*) as awards,
                       ROUND(SUM(awd_amount) / 1e6, 2) as total_m
                FROM awards
                WHERE {where} AND inst_state_code IS NOT NULL
                GROUP BY inst_state_code""",
            conn,
            params=params,
        )
    return df


@st.cache_data(ttl=3600)
def get_my_institution_rank(inst_search, source, division=None, subdiv=None,
                            program=None, institute=None,
                            activity_code=None, cfda=None) -> dict | None:
    where, params = _build_filter(source, division, subdiv, program, institute,
                                  activity_code, cfda)
    with _conn() as conn:
        # All institutions ranked
        rows = conn.execute(
            f"""SELECT inst_name,
                       COUNT(*) as awards,
                       ROUND(SUM(awd_amount) / 1e6, 2) as total_m
                FROM awards WHERE {where}
                GROUP BY inst_name ORDER BY total_m DESC""",
            params,
        ).fetchall()

    search_upper = inst_search.upper()
    for rank, (name, awards, total) in enumerate(rows, 1):
        if name and search_upper in name.upper():
            return {
                "name": name,
                "rank": rank,
                "total": len(rows),
                "awards": awards,
                "total_m": total,
            }
    return None


@st.cache_data(ttl=3600)
def get_gap_programs(division, my_institution, min_peer_awards=3,
                     use_div_abbr=False) -> pd.DataFrame:
    """NSF only: programs where peers win but my institution has 0 awards.

    division: dir_abbr value normally; pass use_div_abbr=True if it's a div_abbr.
    """
    inst_upper = f"%{my_institution.upper()}%"
    col = "div_abbr" if use_div_abbr else "dir_abbr"
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT pgm_ele_name as Program,
                      COUNT(DISTINCT inst_name) as Institutions,
                      COUNT(*) as Awards,
                      ROUND(SUM(awd_amount) / 1e6, 1) as [Total ($M)],
                      ROUND(AVG(awd_amount) / 1e6, 3) as [Avg ($M)]
               FROM awards
               WHERE source = 'nsf' AND {col} = ?
               AND pgm_ele_name IS NOT NULL
               AND pgm_ele_name NOT IN (
                   SELECT DISTINCT pgm_ele_name FROM awards
                   WHERE source = 'nsf' AND {col} = ?
                   AND UPPER(inst_name) LIKE ?
               )
               GROUP BY pgm_ele_name
               HAVING Institutions >= ?
               ORDER BY [Total ($M)] DESC
               LIMIT 10""",
            conn,
            params=(division, division, inst_upper, min_peer_awards),
        )
    return df


# ---------------------------------------------------------------------------
# Institution Breakdown queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def search_institutions(query: str, limit=20) -> list[str]:
    """Search by canonical name (deduped across sources)."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT canonical_name FROM institutions
               WHERE UPPER(canonical_name) LIKE ?
               ORDER BY canonical_name LIMIT ?""",
            (f"%{query.upper()}%", limit),
        ).fetchall()
    return [r[0] for r in rows if r[0]]


@st.cache_data(ttl=3600)
def get_institution_summary(inst_name: str) -> dict:
    ed_clause, ed_params = _ed_exclusion_clause()
    with _conn() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) as awards,
                      ROUND(SUM(awd_amount) / 1e6, 2) as total_m,
                      COUNT(DISTINCT source) as agencies,
                      MIN(fiscal_year) as first_fy,
                      MAX(fiscal_year) as last_fy
               FROM awards WHERE inst_canonical_name = ? AND {ed_clause}""",
            (inst_name, *ed_params),
        ).fetchone()
    return {
        "awards": row[0], "total_m": row[1],
        "agencies": row[2], "first_fy": row[3], "last_fy": row[4],
    }


@st.cache_data(ttl=3600)
def get_institution_by_agency(inst_name: str) -> pd.DataFrame:
    ed_clause, ed_params = _ed_exclusion_clause()
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT source as Agency,
                      COUNT(*) as Awards,
                      ROUND(SUM(awd_amount) / 1e6, 2) as [Total ($M)],
                      MIN(fiscal_year) as [First FY],
                      MAX(fiscal_year) as [Last FY]
               FROM awards WHERE inst_canonical_name = ? AND {ed_clause}
               GROUP BY source ORDER BY [Total ($M)] DESC""",
            conn, params=(inst_name, *ed_params),
        )
    return df


@st.cache_data(ttl=3600)
def get_institution_trend(inst_name: str) -> pd.DataFrame:
    ed_clause, ed_params = _ed_exclusion_clause()
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT fiscal_year, source,
                      ROUND(SUM(awd_amount) / 1e6, 2) as total_m
               FROM awards
               WHERE inst_canonical_name = ? AND fiscal_year IS NOT NULL
                 AND {ed_clause}
               GROUP BY fiscal_year, source
               ORDER BY fiscal_year""",
            conn, params=(inst_name, *ed_params),
        )
    return df


@st.cache_data(ttl=3600)
def get_scoped_pis(
    inst_name: str,
    agency: str,
    fy_start: int,
    fy_end: int,
    dir_filter: str | None = None,
    subdiv_filter: str | None = None,
    institute_filter: str | None = None,
) -> pd.DataFrame:
    """PIs at an institution filtered to current agency/scope/FY selection."""
    clauses = [
        "inst_canonical_name = ?",
        "source = ?",
        "fiscal_year BETWEEN ? AND ?",
        "awd_amount > 0",
        "pi_name IS NOT NULL",
        "pi_name != ''",
    ]
    params: list = [inst_name, agency, fy_start, fy_end]
    if agency == "ed":
        ed_clause, ed_params = _ed_exclusion_clause()
        clauses.append(ed_clause)
        params.extend(ed_params)

    if agency == "nih":
        extra_select = "nih_institute, activity_code,"
        extra_group = ", nih_institute, activity_code"
        if institute_filter:
            clauses.append("nih_institute = ?")
            params.append(institute_filter)
    elif agency == "nsf":
        extra_select = "dir_abbr, div_abbr, pgm_ele_name,"
        extra_group = ", dir_abbr, div_abbr, pgm_ele_name"
        if dir_filter:
            clauses.append("dir_abbr = ?")
            params.append(dir_filter)
        if subdiv_filter:
            clauses.append("div_abbr = ?")
            params.append(subdiv_filter)
    else:
        extra_select = ""
        extra_group = ""

    where = " AND ".join(clauses)
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT pi_name AS PI,
                       {extra_select}
                       COUNT(*) AS Awards,
                       ROUND(SUM(awd_amount) / 1e6, 2) AS [Total ($M)],
                       MIN(fiscal_year) AS [First FY],
                       MAX(fiscal_year) AS [Last FY]
                FROM awards
                WHERE {where}
                GROUP BY pi_name{extra_group}
                ORDER BY [Total ($M)] DESC""",
            conn, params=params,
        )
    # Deduplicate to top-funded row per PI (primary program combination)
    if not df.empty:
        df = df.drop_duplicates(subset=["PI"], keep="first")
    return df


@st.cache_data(ttl=3600)
def get_institution_pis(inst_name: str, source: str | None = None) -> pd.DataFrame:
    ed_clause, ed_params = _ed_exclusion_clause()
    params = [inst_name]
    source_clause = ""
    if source:
        source_clause = "AND source = ?"
        params.append(source)
    params.extend(ed_params)
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT pi_name as PI,
                       source as Agency,
                       COUNT(*) as Awards,
                       ROUND(SUM(awd_amount) / 1e6, 2) as [Total ($M)],
                       MIN(fiscal_year) as [First FY],
                       MAX(fiscal_year) as [Last FY],
                       GROUP_CONCAT(DISTINCT dir_abbr) as Divisions
                FROM awards
                WHERE inst_canonical_name = ? {source_clause}
                AND pi_name IS NOT NULL AND pi_name != ''
                AND {ed_clause}
                GROUP BY pi_name, source
                ORDER BY [Total ($M)] DESC""",
            conn, params=params,
        )
    return df


@st.cache_data(ttl=3600)
def get_institution_awards(inst_name: str, source: str | None = None,
                           fy: int | None = None) -> pd.DataFrame:
    ed_clause, ed_params = _ed_exclusion_clause()
    clauses = ["inst_canonical_name = ?"]
    params = [inst_name]
    if source:
        clauses.append("source = ?")
        params.append(source)
    if fy:
        clauses.append("fiscal_year = ?")
        params.append(fy)
    clauses.append(ed_clause)
    params.extend(ed_params)
    where = " AND ".join(clauses)
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT awd_id as ID,
                       fiscal_year as FY,
                       source as Agency,
                       dir_abbr as Division,
                       ROUND(awd_amount / 1e6, 3) as [Amount ($M)],
                       pi_name as PI,
                       awd_titl_txt as Title
                FROM awards WHERE {where}
                ORDER BY fiscal_year DESC, awd_amount DESC""",
            conn, params=params,
        )
    return df


# ---------------------------------------------------------------------------
# Peer / gap analysis queries (used by new Home.py)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_my_ueis() -> list[str]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT inst_uei FROM institutions WHERE is_my_institution = 1"
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=3600)
def get_peer_institutions(peer_set: str) -> list[tuple[str, str]]:
    """Returns (peer_label, inst_uei) for UNT's hardcoded peer set."""
    if peer_set == "Texas":
        cond = "is_peer_texas = 1"
    elif peer_set == "National":
        cond = "is_peer_national = 1"
    else:
        cond = "(is_peer_texas = 1 OR is_peer_national = 1)"
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT peer_label, inst_uei FROM institutions"
            f" WHERE {cond} ORDER BY peer_label"
        ).fetchall()
    return rows


@st.cache_data(ttl=3600)
def get_dynamic_peers(
    selected_uei: str,
    peer_set: str,
    k: int = 10,
) -> list[tuple[str, str]]:
    """KNN peers from HERD data: top-k nearest by research expenditure.

    peer_set values:
        "<state>" (e.g. "TX") — same state, same Carnegie, nearest by funding
        "National"            — same Carnegie, any state, nearest by funding
        "Both"                — union of state + national (up to 2k)

    Returns list of (display_name, awards_uei).
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT state, carnegie, awards_total_m FROM herd_institutions WHERE awards_uei = ?",
            (selected_uei,),
        ).fetchone()
        if not row:
            return []
        my_state, my_carnegie, my_funding = row
        my_funding = my_funding or 0.0

        def _fetch_nearest(state_filter: str | None) -> list[tuple[str, str]]:
            if state_filter:
                sql = """
                    SELECT ipeds_name, awards_uei, awards_total_m
                    FROM herd_institutions
                    WHERE awards_uei IS NOT NULL
                      AND awards_uei != ?
                      AND state = ?
                      AND carnegie = ?
                    ORDER BY ABS(awards_total_m - ?) ASC
                    LIMIT ?
                """
                params = (selected_uei, state_filter, my_carnegie, my_funding, k)
            else:
                sql = """
                    SELECT ipeds_name, awards_uei, awards_total_m
                    FROM herd_institutions
                    WHERE awards_uei IS NOT NULL
                      AND awards_uei != ?
                      AND carnegie = ?
                    ORDER BY ABS(awards_total_m - ?) ASC
                    LIMIT ?
                """
                params = (selected_uei, my_carnegie, my_funding, k)
            return [
                (r[0], r[1]) for r in conn.execute(sql, params).fetchall()
            ]

        if peer_set == "National":
            return _fetch_nearest(None)
        elif peer_set == "Both":
            state_peers = _fetch_nearest(my_state)
            national_peers = _fetch_nearest(None)
            # Merge, deduplicate, preserve order
            seen = set()
            merged = []
            for item in state_peers + national_peers:
                if item[1] not in seen:
                    seen.add(item[1])
                    merged.append(item)
            return merged
        else:
            # peer_set is a state abbreviation
            return _fetch_nearest(my_state)


@st.cache_data(ttl=3600)
def get_institution_state(awards_uei: str) -> str | None:
    """Return the two-letter state code for an institution."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT state FROM herd_institutions WHERE awards_uei = ?",
            (awards_uei,),
        ).fetchone()
    return row[0] if row else None


@st.cache_data(ttl=3600)
def get_historical_avg_by_agency(
    inst_ueis: tuple[str, ...],
    fy_start: int,
    fy_end: int,
) -> pd.DataFrame:
    """3-year trailing average of research-only awards by agency.

    Returns DataFrame: source | avg_awards | avg_funding_m | total_funding_m
    ED non-research CFDAs are excluded automatically.
    """
    if not inst_ueis:
        return pd.DataFrame()

    uei_ph = ",".join("?" * len(inst_ueis))
    ed_ph = ",".join("?" * len(ED_NON_RESEARCH_CFDAS))
    n_years = fy_end - fy_start + 1

    sql = f"""
        SELECT source,
               COUNT(*)                      AS total_awards,
               ROUND(SUM(awd_amount)/1e6, 2) AS total_funding_m
        FROM awards
        WHERE inst_uei IN ({uei_ph})
          AND fiscal_year BETWEEN ? AND ?
          AND awd_amount > 0
          AND NOT (source = 'ed' AND opportunity_number IN ({ed_ph}))
        GROUP BY source
        ORDER BY total_funding_m DESC
    """
    params = list(inst_ueis) + [fy_start, fy_end] + list(ED_NON_RESEARCH_CFDAS)

    with _conn() as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if df.empty:
        return df

    df["avg_awards"] = (df["total_awards"] / n_years).round(1)
    df["avg_funding_m"] = (df["total_funding_m"] / n_years).round(2)
    return df


@st.cache_data(ttl=3600)
def get_historical_funding_by_fy(
    inst_ueis: tuple[str, ...],
    fy_start: int,
    fy_end: int,
) -> pd.DataFrame:
    """Annual research-only funding totals for an institution.

    Returns DataFrame: fiscal_year | awards | funding_m
    """
    if not inst_ueis:
        return pd.DataFrame()

    uei_ph = ",".join("?" * len(inst_ueis))
    ed_ph = ",".join("?" * len(ED_NON_RESEARCH_CFDAS))

    sql = f"""
        SELECT fiscal_year,
               COUNT(*)                      AS awards,
               ROUND(SUM(awd_amount)/1e6, 2) AS funding_m
        FROM awards
        WHERE inst_uei IN ({uei_ph})
          AND fiscal_year BETWEEN ? AND ?
          AND awd_amount > 0
          AND NOT (source = 'ed' AND opportunity_number IN ({ed_ph}))
        GROUP BY fiscal_year
        ORDER BY fiscal_year
    """
    params = list(inst_ueis) + [fy_start, fy_end] + list(ED_NON_RESEARCH_CFDAS)

    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=3600)
def get_fy_bounds() -> tuple[int, int]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT MIN(fiscal_year), MAX(fiscal_year)"
            " FROM awards WHERE fiscal_year IS NOT NULL"
        ).fetchone()
    return int(row[0]), int(row[1])


@st.cache_data(ttl=3600)
def get_field_wide_stats(
    agency: str,
    fy_start: int,
    fy_end: int,
    dir_filter: str | None = None,
    subdiv_filter: str | None = None,
    institute_filter: str | None = None,
    cfda_filter: str | None = None,
    ed_exclude_cfdas: tuple[str, ...] = (),
) -> pd.DataFrame:
    """
    Field-wide totals per program (ALL institutions, not just peers).
    Returns: program_abbr | field_awards | last_funded
    """
    if agency == "nsf":
        if subdiv_filter:
            prog_col = "pgm_ele_name"
            name_expr = "pgm_ele_name"
        elif dir_filter:
            prog_col = "div_abbr"
            name_expr = "COALESCE(div_full_name, div_abbr)"
        else:
            prog_col = "dir_abbr"
            name_expr = "COALESCE(dir_full_name, dir_abbr)"
    elif agency == "nih":
        prog_col = "activity_code" if institute_filter else "nih_institute"
        name_expr = prog_col
    else:
        prog_col  = "opportunity_number"
        name_expr = "COALESCE(cfda_title, opportunity_number)"

    clauses = [
        "source = ?",
        "fiscal_year BETWEEN ? AND ?",
        f"{prog_col} IS NOT NULL",
        f"TRIM({prog_col}) != ''",
        "awd_amount > 0",
    ]
    params: list = [agency, fy_start, fy_end]

    if agency == "nsf":
        if dir_filter:
            clauses.append("dir_abbr = ?")
            params.append(dir_filter)
        if subdiv_filter:
            clauses.append("div_abbr = ?")
            params.append(subdiv_filter)
    elif agency == "nih" and institute_filter:
        clauses.append("nih_institute = ?")
        params.append(institute_filter)

    if cfda_filter:
        clauses.append("opportunity_number = ?")
        params.append(cfda_filter)
    if ed_exclude_cfdas:
        placeholders_ed = ",".join("?" * len(ed_exclude_cfdas))
        clauses.append(f"opportunity_number NOT IN ({placeholders_ed})")
        params.extend(ed_exclude_cfdas)

    sql = f"""
        SELECT {prog_col} AS program_abbr,
               COUNT(*) AS field_awards,
               MAX(fiscal_year) AS last_funded,
               SUM(CASE WHEN fiscal_year = {fy_end}     THEN 1 ELSE 0 END) AS awards_current,
               SUM(CASE WHEN fiscal_year = {fy_end - 1} THEN 1 ELSE 0 END) AS awards_prev,
               SUM(CASE WHEN fiscal_year = {fy_end - 2} THEN 1 ELSE 0 END) AS awards_two_ago
        FROM awards
        WHERE {" AND ".join(clauses)}
        GROUP BY {prog_col}
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=3600)
def get_heatmap_data(
    my_ueis: tuple[str, ...],
    agency: str,
    fy_start: int,
    fy_end: int,
    dir_filter: str | None = None,
    subdiv_filter: str | None = None,
    institute_filter: str | None = None,
    cfda_filter: str | None = None,
    ed_exclude_cfdas: tuple[str, ...] = (),
) -> pd.DataFrame:
    """
    Program × fiscal_year matrix for the heatmap.
    Returns: program_abbr | program | fiscal_year | field_awards | field_funding_m | unt_awards
    """
    if agency == "nsf":
        if subdiv_filter:
            prog_col  = "pgm_ele_name"
            name_expr = "pgm_ele_name"
        elif dir_filter:
            prog_col  = "div_abbr"
            name_expr = "COALESCE(div_full_name, div_abbr)"
        else:
            prog_col  = "dir_abbr"
            name_expr = "COALESCE(dir_full_name, dir_abbr)"
    elif agency == "nih":
        prog_col  = "activity_code" if institute_filter else "nih_institute"
        name_expr = prog_col
    else:
        prog_col  = "opportunity_number"
        name_expr = "COALESCE(cfda_title, opportunity_number)"

    clauses = [
        "source = ?",
        "fiscal_year BETWEEN ? AND ?",
        f"{prog_col} IS NOT NULL",
        f"TRIM({prog_col}) != ''",
        "awd_amount > 0",
    ]
    params: list = [agency, fy_start, fy_end]

    if agency == "nsf":
        if dir_filter:
            clauses.append("dir_abbr = ?")
            params.append(dir_filter)
        if subdiv_filter:
            clauses.append("div_abbr = ?")
            params.append(subdiv_filter)
    elif agency == "nih" and institute_filter:
        clauses.append("nih_institute = ?")
        params.append(institute_filter)

    if cfda_filter:
        clauses.append("opportunity_number = ?")
        params.append(cfda_filter)
    if ed_exclude_cfdas:
        placeholders_ed = ",".join("?" * len(ed_exclude_cfdas))
        clauses.append(f"opportunity_number NOT IN ({placeholders_ed})")
        params.extend(ed_exclude_cfdas)

    uei_ph = ",".join("?" * len(my_ueis)) if my_ueis else "NULL"
    # UEI placeholders appear twice in SELECT (unt_awards + unt_funding_m), so UEI params doubled
    params_full = list(my_ueis) + list(my_ueis) + params

    sql = f"""
        SELECT {prog_col} AS program_abbr,
               {name_expr} AS program,
               fiscal_year,
               COUNT(*) AS field_awards,
               ROUND(COALESCE(SUM(awd_amount), 0) / 1e6, 2) AS field_funding_m,
               SUM(CASE WHEN inst_uei IN ({uei_ph}) THEN 1 ELSE 0 END) AS unt_awards,
               ROUND(COALESCE(SUM(CASE WHEN inst_uei IN ({uei_ph}) THEN awd_amount ELSE 0 END), 0) / 1e6, 2) AS unt_funding_m
        FROM awards
        WHERE {" AND ".join(clauses)}
        GROUP BY {prog_col}, fiscal_year
        ORDER BY {prog_col}, fiscal_year
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params_full)


@st.cache_data(ttl=3600)
def get_raw_comparison(
    my_ueis: tuple[str, ...],
    peer_ueis: tuple[str, ...],
    agency: str,
    fy_start: int,
    fy_end: int,
    dir_filter: str | None = None,
    subdiv_filter: str | None = None,
    institute_filter: str | None = None,
    cfda_filter: str | None = None,
    ed_exclude_cfdas: tuple[str, ...] = (),
) -> pd.DataFrame:
    """
    Long-form DataFrame: program | institution | awards | funding_m
    for UNT + all peers combined. Used to build the gap table in Home.py.
    """
    all_ueis = my_ueis + peer_ueis
    if not all_ueis:
        return pd.DataFrame()

    # Determine program grouping column
    if agency == "nsf":
        if subdiv_filter:
            prog_col = "pgm_ele_name"
        elif dir_filter:
            prog_col = "div_abbr"
        else:
            prog_col = "dir_abbr"
    elif agency == "nih":
        prog_col  = "activity_code" if institute_filter else "nih_institute"
        name_expr = prog_col
    else:
        prog_col  = "opportunity_number"
        name_expr = "COALESCE(cfda_title, opportunity_number)"

    placeholders = ",".join("?" * len(all_ueis))
    clauses = [
        "source = ?",
        "fiscal_year BETWEEN ? AND ?",
        f"inst_uei IN ({placeholders})",
        f"{prog_col} IS NOT NULL",
        f"TRIM({prog_col}) != ''",
        "awd_amount > 0",
    ]
    params: list = [agency, fy_start, fy_end] + list(all_ueis)

    if agency == "nsf":
        if dir_filter:
            clauses.append("dir_abbr = ?")
            params.append(dir_filter)
        if subdiv_filter:
            clauses.append("div_abbr = ?")
            params.append(subdiv_filter)
        # Include full name column where available
        if prog_col == "dir_abbr":
            name_expr = "COALESCE(dir_full_name, dir_abbr)"
        elif prog_col == "div_abbr":
            name_expr = "COALESCE(div_full_name, div_abbr)"
        else:
            name_expr = prog_col
    elif agency == "nih" and institute_filter:
        clauses.append("nih_institute = ?")
        params.append(institute_filter)

    if cfda_filter:
        clauses.append("opportunity_number = ?")
        params.append(cfda_filter)
    if ed_exclude_cfdas:
        placeholders_ed = ",".join("?" * len(ed_exclude_cfdas))
        clauses.append(f"opportunity_number NOT IN ({placeholders_ed})")
        params.extend(ed_exclude_cfdas)

    sql = f"""
        SELECT {prog_col} AS program_abbr,
               {name_expr} AS program,
               inst_canonical_name AS institution,
               COUNT(*) AS awards,
               ROUND(COALESCE(SUM(awd_amount), 0) / 1e6, 3) AS funding_m
        FROM awards
        WHERE {" AND ".join(clauses)}
          AND inst_canonical_name IS NOT NULL
        GROUP BY {prog_col}, inst_canonical_name
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=3600)
def get_raw_comparison_by_fy(
    my_ueis: tuple[str, ...],
    peer_ueis: tuple[str, ...],
    agency: str,
    fy_start: int,
    fy_end: int,
    dir_filter: str | None = None,
    subdiv_filter: str | None = None,
    institute_filter: str | None = None,
    cfda_filter: str | None = None,
    ed_exclude_cfdas: tuple[str, ...] = (),
) -> pd.DataFrame:
    """
    Like get_raw_comparison but grouped by program × institution × fiscal_year.
    Returns: program_abbr | program | institution | fiscal_year | awards | funding_m
    """
    all_ueis = my_ueis + peer_ueis
    if not all_ueis:
        return pd.DataFrame()

    if agency == "nsf":
        if subdiv_filter:
            prog_col = "pgm_ele_name"
        elif dir_filter:
            prog_col = "div_abbr"
        else:
            prog_col = "dir_abbr"
    elif agency == "nih":
        prog_col = "activity_code" if institute_filter else "nih_institute"
        name_expr = prog_col
    else:
        prog_col = "opportunity_number"
        name_expr = "COALESCE(cfda_title, opportunity_number)"

    placeholders = ",".join("?" * len(all_ueis))
    clauses = [
        "source = ?",
        "fiscal_year BETWEEN ? AND ?",
        f"inst_uei IN ({placeholders})",
        f"{prog_col} IS NOT NULL",
        f"TRIM({prog_col}) != ''",
        "awd_amount > 0",
    ]
    params: list = [agency, fy_start, fy_end] + list(all_ueis)

    if agency == "nsf":
        if dir_filter:
            clauses.append("dir_abbr = ?")
            params.append(dir_filter)
        if subdiv_filter:
            clauses.append("div_abbr = ?")
            params.append(subdiv_filter)
        if prog_col == "dir_abbr":
            name_expr = "COALESCE(dir_full_name, dir_abbr)"
        elif prog_col == "div_abbr":
            name_expr = "COALESCE(div_full_name, div_abbr)"
        else:
            name_expr = prog_col
    elif agency == "nih" and institute_filter:
        clauses.append("nih_institute = ?")
        params.append(institute_filter)

    if cfda_filter:
        clauses.append("opportunity_number = ?")
        params.append(cfda_filter)
    if ed_exclude_cfdas:
        placeholders_ed = ",".join("?" * len(ed_exclude_cfdas))
        clauses.append(f"opportunity_number NOT IN ({placeholders_ed})")
        params.extend(ed_exclude_cfdas)

    sql = f"""
        SELECT {prog_col} AS program_abbr,
               {name_expr} AS program,
               inst_canonical_name AS institution,
               fiscal_year,
               COUNT(*) AS awards,
               ROUND(COALESCE(SUM(awd_amount), 0) / 1e6, 3) AS funding_m
        FROM awards
        WHERE {" AND ".join(clauses)}
          AND inst_canonical_name IS NOT NULL
        GROUP BY {prog_col}, inst_canonical_name, fiscal_year
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


# ---------------------------------------------------------------------------
# PI drill-down + validation stats
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_pis_for_program(
    institution: str,
    agency: str,
    prog_col: str,
    program_abbr: str,
    fy_start: int,
    fy_end: int,
) -> pd.DataFrame:
    """PIs at a given institution who won awards in a specific program."""
    ed_clause, ed_params = _ed_exclusion_clause()
    sql = f"""
        SELECT pi_name AS PI,
               COUNT(*) AS Awards,
               COALESCE(SUM(awd_amount), 0) AS [Total Funding],
               MIN(fiscal_year) AS [First FY],
               MAX(fiscal_year) AS [Last FY]
        FROM awards
        WHERE source = ?
          AND {prog_col} = ?
          AND inst_canonical_name = ?
          AND fiscal_year BETWEEN ? AND ?
          AND awd_amount > 0
          AND pi_name IS NOT NULL AND pi_name != ''
          AND {ed_clause}
        GROUP BY pi_name
        ORDER BY [Total Funding] DESC
    """
    with _conn() as conn:
        df = pd.read_sql_query(
            sql, conn, params=(agency, program_abbr, institution, fy_start, fy_end, *ed_params)
        )
    df.index = range(1, len(df) + 1)
    # Keep FY columns as plain integers (not formatted as 2,024)
    for col in ("First FY", "Last FY"):
        if col in df.columns:
            df[col] = df[col].astype(int)
    return df


@st.cache_data(ttl=3600)
def get_validation_stats(agency: str, fy_start: int, fy_end: int) -> dict:
    """Summary stats for the validation footer."""
    ed_clause, ed_params = _ed_exclusion_clause()
    with _conn() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) AS total_records,
                      ROUND(COALESCE(SUM(awd_amount), 0) / 1e6, 1) AS total_funding_m,
                      MAX(updated_at) AS last_new_record,
                      SUM(CASE WHEN awd_amount < 0 THEN 1 ELSE 0 END) AS negative_excluded,
                      SUM(CASE WHEN awd_amount = 0 THEN 1 ELSE 0 END) AS zero_count
               FROM awards
               WHERE source = ? AND fiscal_year BETWEEN ? AND ?
                 AND {ed_clause}""",
            (agency, fy_start, fy_end, *ed_params),
        ).fetchone()
        # NSF and NIH log under their own name; all USASpending agencies
        # log under the single key 'usaspending'
        _NSF_NIH = {"nsf", "nih"}
        log_source = agency if agency in _NSF_NIH else "usaspending"
        refresh_row = conn.execute(
            """SELECT MAX(finished_at) FROM refresh_log
               WHERE source = ? AND status = 'success'""",
            (log_source,),
        ).fetchone()
    last_checked = refresh_row[0] if refresh_row and refresh_row[0] else None
    return {
        "total_records": row[0],
        "total_funding_m": row[1],
        "last_new_record": row[2],
        "last_checked": last_checked,
        "negative_excluded": row[3],
        "zero_count": row[4],
    }


@st.cache_data(ttl=3600)
def get_recent_ingestion_activity(days: int = 7) -> pd.DataFrame:
    """Per-agency, per-day count of newly inserted awards (not updates) and
    the $ they add, over the last `days` days.

    Uses created_at (set once at INSERT, never touched again by the upsert's
    ON CONFLICT branch) rather than updated_at (touched on every upsert,
    including re-fetches of unchanged records) — this is the ground-truth
    signal that new data actually landed, not just that a job ran.
    """
    with _conn() as conn:
        df = pd.read_sql_query(
            """SELECT DATE(created_at) AS day,
                      source AS agency,
                      COUNT(*) AS new_records,
                      ROUND(SUM(awd_amount) / 1e6, 2) AS new_funding_m
               FROM awards
               WHERE created_at >= DATE('now', ?)
               GROUP BY day, agency
               ORDER BY day DESC, agency""",
            conn, params=(f"-{days} days",),
        )
    return df


# ---------------------------------------------------------------------------
# Portfolio Risk queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_portfolio_by_agency(inst_name: str, fy_start: int, fy_end: int) -> pd.DataFrame:
    """Funding breakdown by agency for one institution.
    Returns: source | awards | funding_m
    """
    ed_clause, ed_params = _ed_exclusion_clause()
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT source,
                      COUNT(*) AS awards,
                      ROUND(SUM(awd_amount) / 1e6, 2) AS funding_m
               FROM awards
               WHERE inst_canonical_name = ?
                 AND fiscal_year BETWEEN ? AND ?
                 AND awd_amount > 0
                 AND {ed_clause}
               GROUP BY source
               ORDER BY funding_m DESC""",
            conn, params=(inst_name, fy_start, fy_end, *ed_params),
        )
    return df


@st.cache_data(ttl=3600)
def get_portfolio_trend(inst_name: str, fy_start: int, fy_end: int) -> pd.DataFrame:
    """Funding by agency and FY for one institution.
    Returns: fiscal_year | source | funding_m
    """
    ed_clause, ed_params = _ed_exclusion_clause()
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT fiscal_year, source,
                      ROUND(SUM(awd_amount) / 1e6, 2) AS funding_m
               FROM awards
               WHERE inst_canonical_name = ?
                 AND fiscal_year BETWEEN ? AND ?
                 AND awd_amount > 0
                 AND fiscal_year IS NOT NULL
                 AND {ed_clause}
               GROUP BY fiscal_year, source
               ORDER BY fiscal_year, source""",
            conn, params=(inst_name, fy_start, fy_end, *ed_params),
        )
    return df


@st.cache_data(ttl=3600)
def get_peer_diversification(inst_names: tuple[str, ...],
                             fy_start: int, fy_end: int) -> pd.DataFrame:
    """Concentration metrics per institution.
    Returns: institution | top_source | top_pct | n_sources | hhi
    """
    if not inst_names:
        return pd.DataFrame()
    ed_clause, ed_params = _ed_exclusion_clause()
    placeholders = ",".join("?" * len(inst_names))
    sql = f"""
        SELECT inst_canonical_name AS institution, source,
               SUM(awd_amount) AS funding
        FROM awards
        WHERE inst_canonical_name IN ({placeholders})
          AND fiscal_year BETWEEN ? AND ?
          AND awd_amount > 0
          AND {ed_clause}
        GROUP BY inst_canonical_name, source
    """
    params = list(inst_names) + [fy_start, fy_end] + ed_params
    with _conn() as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        return pd.DataFrame()

    rows = []
    for inst, grp in df.groupby("institution"):
        total = grp["funding"].sum()
        if total <= 0:
            continue
        grp = grp.copy()
        grp["share"] = grp["funding"] / total
        top = grp.loc[grp["share"].idxmax()]
        hhi = round((grp["share"] ** 2).sum(), 4)
        rows.append({
            "institution": inst,
            "top_source": top["source"],
            "top_pct": round(top["share"] * 100, 1),
            "n_sources": len(grp),
            "hhi": hhi,
        })
    return pd.DataFrame(rows).sort_values("top_pct", ascending=False)


# ---------------------------------------------------------------------------
# Expiring Awards queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_expiring_awards(inst_name: str, horizon_date: str,
                        agency: str | None = None) -> pd.DataFrame:
    """Awards ending between today and horizon_date.
    Returns: awd_id | pi_name | source | program | awd_amount | project_end_date | title
    """
    ed_clause, ed_params = _ed_exclusion_clause()
    clauses = [
        "inst_canonical_name = ?",
        "project_end_date >= date('now')",
        "project_end_date <= ?",
        "awd_amount > 0",
        ed_clause,
    ]
    params: list = [inst_name, horizon_date, *ed_params]
    if agency:
        clauses.append("source = ?")
        params.append(agency)
    where = " AND ".join(clauses)
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT awd_id,
                       pi_name,
                       source,
                       CASE
                         WHEN source = 'nsf' THEN dir_abbr
                         WHEN source = 'nih' THEN nih_institute
                         ELSE opportunity_number
                       END AS program,
                       awd_amount,
                       project_end_date,
                       awd_titl_txt AS title
                FROM awards
                WHERE {where}
                ORDER BY project_end_date""",
            conn, params=params,
        )
    return df


@st.cache_data(ttl=3600)
def get_expiring_summary(inst_name: str, horizon_date: str,
                         agency: str | None = None) -> dict:
    """Aggregate stats for expiring awards scorecard."""
    ed_clause, ed_params = _ed_exclusion_clause()
    clauses = [
        "inst_canonical_name = ?",
        "project_end_date >= date('now')",
        "project_end_date <= ?",
        "awd_amount > 0",
        ed_clause,
    ]
    params: list = [inst_name, horizon_date, *ed_params]
    if agency:
        clauses.append("source = ?")
        params.append(agency)
    where = " AND ".join(clauses)
    with _conn() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) AS total_awards,
                       ROUND(COALESCE(SUM(awd_amount), 0) / 1e6, 2) AS total_funding_m,
                       ROUND(COALESCE(MAX(awd_amount), 0) / 1e6, 2) AS largest_award_m,
                       COUNT(DISTINCT CASE WHEN pi_name IS NOT NULL AND pi_name != ''
                                           THEN pi_name END) AS pis_affected
                FROM awards
                WHERE {where}""",
            params,
        ).fetchone()
    return {
        "total_awards": row[0],
        "total_funding_m": row[1],
        "largest_award_m": row[2],
        "pis_affected": row[3],
    }


# ---------------------------------------------------------------------------
# Action Dashboard queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_agency_money_movement(
    my_ueis: tuple[str, ...],
    peer_ueis: tuple[str, ...],
) -> pd.DataFrame:
    """FY2025 YTD vs FY2026 YTD per agency, apples-to-apples month cutoff.

    Federal FY runs Oct–Sep.  We find the latest obligation month in FY2026
    and restrict FY2025 to the same Oct-through-Month window so the
    comparison is fair.  FY2025 "rest of year" (months after the cutoff)
    is returned separately so the VPR can see what's still potentially
    coming in FY2026.

    Returns: source | fy25_ytd_m | fy25_rest_m | fy26_ytd_m |
             pct_change | unt_fy25_m | unt_fy26_m
    """
    if not my_ueis:
        return pd.DataFrame()

    uei_ph_my = ",".join("?" * len(my_ueis)) if my_ueis else "NULL"

    # Find the latest obligation_date in FY2026 to set the cutoff.
    # FY2025 starts 2024-10-01; FY2026 starts 2025-10-01.
    # We'll compare the same calendar window: FY-start through cutoff date.
    with _conn() as conn:
        row = conn.execute(
            "SELECT MAX(obligation_date) "
            "FROM awards WHERE fiscal_year = 2026 AND obligation_date IS NOT NULL "
            "AND awd_amount > 0"
        ).fetchone()
    fy26_latest = row[0] if row and row[0] else "2026-05-31"

    # Extract month-day to build the FY25 cutoff at the same point
    # e.g. if FY26 latest is 2026-05-31, FY25 cutoff is 2025-05-31
    cutoff_mmdd = fy26_latest[5:]  # "05-31"
    fy25_ytd_end = f"2025-{cutoff_mmdd}"
    fy25_rest_start = f"2025-{cutoff_mmdd}"

    ed_clause, ed_params = _ed_exclusion_clause()
    sql = f"""
        SELECT source,
               ROUND(COALESCE(SUM(CASE WHEN fiscal_year = 2025
                   AND obligation_date <= ?
                   THEN awd_amount ELSE 0 END), 0) / 1e6, 2)   AS fy25_ytd_m,
               ROUND(COALESCE(SUM(CASE WHEN fiscal_year = 2025
                   AND obligation_date > ?
                   THEN awd_amount ELSE 0 END), 0) / 1e6, 2)   AS fy25_rest_m,
               ROUND(COALESCE(SUM(CASE WHEN fiscal_year = 2026
                   THEN awd_amount ELSE 0 END), 0) / 1e6, 2)   AS fy26_ytd_m,
               ROUND(COALESCE(SUM(CASE WHEN fiscal_year = 2025
                   AND obligation_date <= ?
                   AND inst_uei IN ({uei_ph_my})
                   THEN awd_amount ELSE 0 END), 0) / 1e6, 2)   AS unt_fy25_m,
               ROUND(COALESCE(SUM(CASE WHEN fiscal_year = 2025
                   AND inst_uei IN ({uei_ph_my})
                   THEN awd_amount ELSE 0 END), 0) / 1e6, 2)   AS unt_fy25_full_m,
               ROUND(COALESCE(SUM(CASE WHEN fiscal_year = 2026
                   AND inst_uei IN ({uei_ph_my})
                   THEN awd_amount ELSE 0 END), 0) / 1e6, 2)   AS unt_fy26_m
        FROM awards
        WHERE fiscal_year IN (2025, 2026)
          AND awd_amount > 0
          AND obligation_date IS NOT NULL
          AND {ed_clause}
        GROUP BY source
        HAVING fy25_ytd_m > 0 OR fy26_ytd_m > 0
        ORDER BY (fy26_ytd_m - fy25_ytd_m) DESC
    """
    params = [fy25_ytd_end, fy25_rest_start, fy25_ytd_end] + list(my_ueis) + list(my_ueis) + list(my_ueis) + ed_params
    with _conn() as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if not df.empty:
        df["change_m"] = df["fy26_ytd_m"] - df["fy25_ytd_m"]
        df["pct_change"] = df.apply(
            lambda r: round((r["fy26_ytd_m"] - r["fy25_ytd_m"]) / r["fy25_ytd_m"] * 100, 1)
            if r["fy25_ytd_m"] > 0 else None, axis=1,
        )
    return df


@st.cache_data(ttl=3600)
def get_missed_opportunities(
    my_ueis: tuple[str, ...],
    peer_ueis: tuple[str, ...],
) -> pd.DataFrame:
    """Programs where peers won FY2025-2026 awards but UNT got nothing.

    Returns: source | opportunity_number | peer_awards | peer_funding_m |
             peer_inst_count | peer_names
    """
    if not my_ueis or not peer_ueis:
        return pd.DataFrame()

    my_ph = ",".join("?" * len(my_ueis))
    peer_ph = ",".join("?" * len(peer_ueis))

    ed_clause, ed_params = _ed_exclusion_clause()
    ed_clause_u, ed_params_u = _ed_exclusion_clause("u")
    sql = f"""
        SELECT p.source,
               p.opportunity_number,
               p.peer_awards,
               p.peer_funding_m,
               p.peer_inst_count,
               p.peer_names
        FROM (
            SELECT source,
                   COALESCE(opportunity_number, dir_abbr, nih_institute) AS opportunity_number,
                   COUNT(*) AS peer_awards,
                   ROUND(SUM(awd_amount) / 1e6, 2) AS peer_funding_m,
                   COUNT(DISTINCT inst_canonical_name) AS peer_inst_count,
                   GROUP_CONCAT(DISTINCT inst_canonical_name) AS peer_names
            FROM awards
            WHERE fiscal_year IN (2025, 2026)
              AND inst_uei IN ({peer_ph})
              AND awd_amount > 0
              AND {ed_clause}
            GROUP BY source, COALESCE(opportunity_number, dir_abbr, nih_institute)
        ) p
        WHERE NOT EXISTS (
            SELECT 1 FROM awards u
            WHERE u.fiscal_year IN (2025, 2026)
              AND u.inst_uei IN ({my_ph})
              AND u.source = p.source
              AND COALESCE(u.opportunity_number, u.dir_abbr, u.nih_institute) = p.opportunity_number
              AND u.awd_amount > 0
              AND {ed_clause_u}
        )
        ORDER BY p.peer_funding_m DESC
    """
    params = list(peer_ueis) + ed_params + list(my_ueis) + ed_params_u
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=3600)
def get_lapsed_programs(my_ueis: tuple[str, ...]) -> pd.DataFrame:
    """Truly dormant programs — UNT won historically (last award FY2022
    or earlier) with no FY2023+ activity.  Filters out noise:
    - min $0.5M past funding
    - excludes ED non-research CFDAs (student aid, CARES, etc.)

    Returns: source | opportunity_number | past_awards | past_funding_m | last_fy
    """
    if not my_ueis:
        return pd.DataFrame()

    my_ph = ",".join("?" * len(my_ueis))
    ed_clause, ed_params = _ed_exclusion_clause()
    ed_clause_r, ed_params_r = _ed_exclusion_clause("r")

    sql = f"""
        SELECT h.source,
               h.prog AS opportunity_number,
               h.past_awards,
               h.past_funding_m,
               h.last_fy
        FROM (
            SELECT source,
                   COALESCE(opportunity_number, dir_abbr, nih_institute) AS prog,
                   COUNT(*) AS past_awards,
                   ROUND(SUM(awd_amount) / 1e6, 2) AS past_funding_m,
                   MAX(fiscal_year) AS last_fy
            FROM awards
            WHERE fiscal_year <= 2022
              AND inst_uei IN ({my_ph})
              AND awd_amount > 0
              AND {ed_clause}
            GROUP BY source, COALESCE(opportunity_number, dir_abbr, nih_institute)
            HAVING past_funding_m >= 0.5
        ) h
        WHERE NOT EXISTS (
            SELECT 1 FROM awards r
            WHERE r.fiscal_year >= 2023
              AND r.inst_uei IN ({my_ph})
              AND r.source = h.source
              AND COALESCE(r.opportunity_number, r.dir_abbr, r.nih_institute) = h.prog
              AND r.awd_amount > 0
              AND {ed_clause_r}
        )
        ORDER BY h.past_funding_m DESC
    """
    params = list(my_ueis) + ed_params + list(my_ueis) + ed_params_r
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=3600)
def get_peer_opportunity_gaps(
    my_ueis: tuple[str, ...],
    peer_ueis: tuple[str, ...],
    status_filter: tuple[str, ...] = ("posted", "forecasted"),
    lookback_fy: int = 2023,
) -> pd.DataFrame:
    """Open/forecasted NOFOs where peers won FY{lookback_fy}+ awards and UNT has no
    recent awards in the same program.

    Two join paths:
      - NIH: awards.opportunity_number = opportunities.opportunity_number (PA/RFA numbers)
      - USASpending: awards.opportunity_number = opportunity_cfdas.cfda_number (CFDA codes)

    Returns one row per opportunity with peer aggregation columns.
    """
    if not my_ueis or not peer_ueis or not status_filter:
        return pd.DataFrame()

    my_ph   = ",".join("?" * len(my_ueis))
    peer_ph = ",".join("?" * len(peer_ueis))
    stat_ph = ",".join("?" * len(status_filter))

    sql = f"""
    WITH peer_opps AS (
        -- NIH: direct opportunity_number match (PA-xx-xxx / RFA-xx-xxx)
        SELECT o.opportunity_id,
               a.inst_canonical_name,
               a.awd_amount,
               a.awd_id
        FROM awards a
        JOIN opportunities o ON a.opportunity_number = o.opportunity_number
        WHERE a.source = 'nih'
          AND a.fiscal_year >= ?
          AND a.inst_uei IN ({peer_ph})
          AND o.derived_status IN ({stat_ph})
        UNION ALL
        -- USASpending: CFDA-number join (11.417, 93.310, …)
        SELECT oc.opportunity_id,
               a.inst_canonical_name,
               a.awd_amount,
               a.awd_id
        FROM awards a
        JOIN opportunity_cfdas oc ON a.opportunity_number = oc.cfda_number
        JOIN opportunities o      ON oc.opportunity_id    = o.opportunity_id
        WHERE a.source NOT IN ('nih', 'nsf')
          AND a.fiscal_year >= ?
          AND a.inst_uei IN ({peer_ph})
          AND o.derived_status IN ({stat_ph})
    ),
    unt_opps AS (
        -- Opportunity IDs where UNT has any FY{lookback_fy}+ award
        SELECT DISTINCT o.opportunity_id
        FROM awards a
        JOIN opportunities o ON a.opportunity_number = o.opportunity_number
        WHERE a.source = 'nih'
          AND a.fiscal_year >= ?
          AND a.inst_uei IN ({my_ph})
        UNION
        SELECT DISTINCT oc.opportunity_id
        FROM awards a
        JOIN opportunity_cfdas oc ON a.opportunity_number = oc.cfda_number
        WHERE a.source NOT IN ('nih', 'nsf')
          AND a.fiscal_year >= ?
          AND a.inst_uei IN ({my_ph})
    ),
    gap_agg AS (
        SELECT
            p.opportunity_id,
            COUNT(DISTINCT p.inst_canonical_name)    AS peer_inst_count,
            COUNT(p.awd_id)                          AS peer_award_count,
            ROUND(SUM(p.awd_amount) / 1e6, 1)        AS peer_total_m,
            GROUP_CONCAT(DISTINCT p.inst_canonical_name) AS peer_names
        FROM peer_opps p
        WHERE p.opportunity_id NOT IN (SELECT opportunity_id FROM unt_opps)
        GROUP BY p.opportunity_id
    )
    SELECT
        o.opportunity_id,
        o.opportunity_number,
        o.opportunity_title,
        o.agency_code,
        o.agency_name,
        o.derived_status,
        o.close_date,
        o.estimated_close_date,
        o.award_ceiling,
        o.expected_number_of_awards,
        o.funding_instrument_type,
        g.peer_inst_count,
        g.peer_award_count,
        g.peer_total_m,
        g.peer_names
    FROM gap_agg g
    JOIN opportunities o ON g.opportunity_id = o.opportunity_id
    ORDER BY
        CASE o.derived_status WHEN 'posted' THEN 0 ELSE 1 END,
        COALESCE(o.close_date, o.estimated_close_date, '9999-99-99') ASC,
        g.peer_total_m DESC
    """

    params = (
        [lookback_fy] + list(peer_ueis) + list(status_filter) +
        [lookback_fy] + list(peer_ueis) + list(status_filter) +
        [lookback_fy] + list(my_ueis) +
        [lookback_fy] + list(my_ueis)
    )

    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=3600)
def get_unt_open_revisits(
    my_ueis: tuple[str, ...],
    status_filter: tuple[str, ...] = ("posted", "forecasted"),
) -> pd.DataFrame:
    """Open/forecasted NOFOs in programs where UNT has any historical award (FY2019+).

    Two join paths:
      - Non-NIH/NSF: awards.opportunity_number (CFDA) → opportunity_cfdas → opportunities
      - NIH: awards.opportunity_number (PA/RFA) → opportunities.opportunity_number

    Returns one row per opportunity with UNT history columns.
    """
    if not my_ueis or not status_filter:
        return pd.DataFrame()

    my_ph   = ",".join("?" * len(my_ueis))
    stat_ph = ",".join("?" * len(status_filter))

    sql = f"""
    WITH unt_cfdas AS (
        SELECT a.opportunity_number                  AS cfda_number,
               COUNT(a.awd_id)                       AS unt_award_count,
               ROUND(SUM(a.awd_amount) / 1e6, 1)     AS unt_total_m,
               MAX(a.fiscal_year)                    AS unt_last_fy
        FROM awards a
        WHERE a.inst_uei IN ({my_ph})
          AND a.source NOT IN ('nih', 'nsf')
          AND a.opportunity_number IS NOT NULL
        GROUP BY a.opportunity_number
    ),
    unt_nih AS (
        SELECT a.opportunity_number,
               COUNT(a.awd_id)                       AS unt_award_count,
               ROUND(SUM(a.awd_amount) / 1e6, 1)     AS unt_total_m,
               MAX(a.fiscal_year)                    AS unt_last_fy
        FROM awards a
        WHERE a.inst_uei IN ({my_ph})
          AND a.source = 'nih'
          AND a.opportunity_number IS NOT NULL
        GROUP BY a.opportunity_number
    )
    SELECT * FROM (
    SELECT o.opportunity_id,
           o.opportunity_number,
           o.opportunity_title,
           o.agency_code,
           o.agency_name,
           o.derived_status,
           o.close_date,
           o.estimated_close_date,
           o.award_ceiling,
           o.expected_number_of_awards,
           uc.unt_award_count,
           uc.unt_total_m,
           uc.unt_last_fy
    FROM unt_cfdas uc
    JOIN opportunity_cfdas ocf ON uc.cfda_number      = ocf.cfda_number
    JOIN opportunities o       ON ocf.opportunity_id  = o.opportunity_id
    WHERE o.derived_status IN ({stat_ph})

    UNION

    SELECT o.opportunity_id,
           o.opportunity_number,
           o.opportunity_title,
           o.agency_code,
           o.agency_name,
           o.derived_status,
           o.close_date,
           o.estimated_close_date,
           o.award_ceiling,
           o.expected_number_of_awards,
           un.unt_award_count,
           un.unt_total_m,
           un.unt_last_fy
    FROM unt_nih un
    JOIN opportunities o ON un.opportunity_number = o.opportunity_number
    WHERE o.derived_status IN ({stat_ph})
    )
    ORDER BY
        CASE derived_status WHEN 'posted' THEN 0 ELSE 1 END,
        unt_last_fy DESC,
        COALESCE(close_date, estimated_close_date, '9999-99-99') ASC
    """

    params = (
        list(my_ueis) +          # unt_cfdas
        list(my_ueis) +          # unt_nih
        list(status_filter) +    # first SELECT WHERE
        list(status_filter)      # second SELECT WHERE
    )

    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=3600)
def get_data_freshness() -> pd.DataFrame:
    """Data freshness: last successful refresh + record counts per source.

    Returns: source | record_count | last_refresh_at | status
    """
    sql = """
        SELECT a.source,
               a.record_count,
               r.finished_at AS last_refresh_at,
               COALESCE(r.status, 'never') AS status
        FROM (
            SELECT source, COUNT(*) AS record_count
            FROM awards GROUP BY source
        ) a
        LEFT JOIN (
            SELECT source, finished_at, status,
                   ROW_NUMBER() OVER (PARTITION BY source ORDER BY finished_at DESC) AS rn
            FROM refresh_log
            WHERE status = 'success'
        ) r ON r.rn = 1
          AND (
              -- NSF and NIH log under their own name
              (a.source IN ('nsf', 'nih') AND r.source = a.source)
              -- All other sources are loaded via USASpending bulk run
              OR (a.source NOT IN ('nsf', 'nih') AND r.source = 'usaspending')
          )
        ORDER BY a.source
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn)
