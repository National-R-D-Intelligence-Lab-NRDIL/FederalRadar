"""
queries.py
All database queries for the Federal Radar Streamlit app.
All results are cached for 1 hour to keep the UI fast.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent.parent / "data" / "federal_awards.db"

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


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA cache_size = -65536;")
    conn.execute("PRAGMA temp_store = MEMORY;")
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
# Program Explorer queries
# ---------------------------------------------------------------------------

def _build_filter(source, division=None, subdiv=None, program=None,
                  institute=None, activity_code=None, cfda=None):
    """Return (WHERE clause, params) for the given filter combination."""
    clauses = ["source = ?"]
    params = [source]
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
    with _conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as awards,
                      ROUND(SUM(awd_amount) / 1e6, 2) as total_m,
                      COUNT(DISTINCT source) as agencies,
                      MIN(fiscal_year) as first_fy,
                      MAX(fiscal_year) as last_fy
               FROM awards WHERE inst_canonical_name = ?""",
            (inst_name,),
        ).fetchone()
    return {
        "awards": row[0], "total_m": row[1],
        "agencies": row[2], "first_fy": row[3], "last_fy": row[4],
    }


@st.cache_data(ttl=3600)
def get_institution_by_agency(inst_name: str) -> pd.DataFrame:
    with _conn() as conn:
        df = pd.read_sql_query(
            """SELECT source as Agency,
                      COUNT(*) as Awards,
                      ROUND(SUM(awd_amount) / 1e6, 2) as [Total ($M)],
                      MIN(fiscal_year) as [First FY],
                      MAX(fiscal_year) as [Last FY]
               FROM awards WHERE inst_canonical_name = ?
               GROUP BY source ORDER BY [Total ($M)] DESC""",
            conn, params=(inst_name,),
        )
    return df


@st.cache_data(ttl=3600)
def get_institution_trend(inst_name: str) -> pd.DataFrame:
    with _conn() as conn:
        df = pd.read_sql_query(
            """SELECT fiscal_year, source,
                      ROUND(SUM(awd_amount) / 1e6, 2) as total_m
               FROM awards
               WHERE inst_canonical_name = ? AND fiscal_year IS NOT NULL
               GROUP BY fiscal_year, source
               ORDER BY fiscal_year""",
            conn, params=(inst_name,),
        )
    return df


@st.cache_data(ttl=3600)
def get_institution_pis(inst_name: str, source: str | None = None) -> pd.DataFrame:
    params = [inst_name]
    source_clause = ""
    if source:
        source_clause = "AND source = ?"
        params.append(source)
    with _conn() as conn:
        df = pd.read_sql_query(
            f"""SELECT pi_name as PI,
                       source as Agency,
                       COUNT(*) as Awards,
                       ROUND(SUM(awd_amount) / 1e6, 2) as [Total ($M)],
                       GROUP_CONCAT(DISTINCT dir_abbr) as Divisions
                FROM awards
                WHERE inst_canonical_name = ? {source_clause}
                AND pi_name IS NOT NULL AND pi_name != ''
                GROUP BY pi_name, source
                ORDER BY [Total ($M)] DESC""",
            conn, params=params,
        )
    return df


@st.cache_data(ttl=3600)
def get_institution_awards(inst_name: str, source: str | None = None,
                           fy: int | None = None) -> pd.DataFrame:
    clauses = ["inst_canonical_name = ?"]
    params = [inst_name]
    if source:
        clauses.append("source = ?")
        params.append(source)
    if fy:
        clauses.append("fiscal_year = ?")
        params.append(fy)
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
    """Returns (peer_label, inst_uei) for the selected peer set."""
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
            name_expr = "COALESCE(json_extract(raw_json,'$.org_div_long_name'), div_abbr)"
        else:
            prog_col = "dir_abbr"
            name_expr = "COALESCE(json_extract(raw_json,'$.org_dir_long_name'), dir_abbr)"
    elif agency == "nih":
        prog_col = "activity_code" if institute_filter else "nih_institute"
        name_expr = prog_col
    else:
        prog_col  = "opportunity_number"
        name_expr = "COALESCE(json_extract(raw_json,'$.cfda_title'), opportunity_number)"

    clauses = [
        "source = ?",
        "fiscal_year BETWEEN ? AND ?",
        f"{prog_col} IS NOT NULL",
        f"TRIM({prog_col}) != ''",
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
            name_expr = "COALESCE(json_extract(raw_json,'$.org_div_long_name'), div_abbr)"
        else:
            prog_col  = "dir_abbr"
            name_expr = "COALESCE(json_extract(raw_json,'$.org_dir_long_name'), dir_abbr)"
    elif agency == "nih":
        prog_col  = "activity_code" if institute_filter else "nih_institute"
        name_expr = prog_col
    else:
        prog_col  = "opportunity_number"
        name_expr = "COALESCE(json_extract(raw_json,'$.cfda_title'), opportunity_number)"

    clauses = [
        "source = ?",
        "fiscal_year BETWEEN ? AND ?",
        f"{prog_col} IS NOT NULL",
        f"TRIM({prog_col}) != ''",
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

    uei_ph = ",".join("?" * len(my_ueis)) if my_ueis else "NULL"
    # UEI placeholders appear in SELECT (before WHERE), so UEI params must come first
    params_full = list(my_ueis) + params

    sql = f"""
        SELECT {prog_col} AS program_abbr,
               {name_expr} AS program,
               fiscal_year,
               COUNT(*) AS field_awards,
               ROUND(COALESCE(SUM(awd_amount), 0) / 1e6, 2) AS field_funding_m,
               SUM(CASE WHEN inst_uei IN ({uei_ph}) THEN 1 ELSE 0 END) AS unt_awards
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
        name_expr = "COALESCE(json_extract(raw_json,'$.cfda_title'), opportunity_number)"

    placeholders = ",".join("?" * len(all_ueis))
    clauses = [
        "source = ?",
        "fiscal_year BETWEEN ? AND ?",
        f"inst_uei IN ({placeholders})",
        f"{prog_col} IS NOT NULL",
        f"TRIM({prog_col}) != ''",
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
            name_expr = "COALESCE(json_extract(raw_json,'$.org_dir_long_name'), dir_abbr)"
        elif prog_col == "div_abbr":
            name_expr = "COALESCE(json_extract(raw_json,'$.org_div_long_name'), div_abbr)"
        else:
            name_expr = prog_col
    elif agency == "nih" and institute_filter:
        clauses.append("nih_institute = ?")
        params.append(institute_filter)

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
