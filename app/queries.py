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
                       COUNT(DISTINCT inst_name) as institutions
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
            f"""SELECT inst_name, inst_state_code,
                       COUNT(*) as awards,
                       ROUND(SUM(awd_amount) / 1e6, 2) as total_m,
                       ROUND(AVG(awd_amount) / 1e6, 3) as avg_m
                FROM awards WHERE {where}
                GROUP BY inst_name
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
    with _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT inst_name FROM awards
               WHERE UPPER(inst_name) LIKE ?
               ORDER BY inst_name LIMIT ?""",
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
               FROM awards WHERE UPPER(inst_name) = UPPER(?)""",
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
               FROM awards WHERE UPPER(inst_name) = UPPER(?)
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
               WHERE UPPER(inst_name) = UPPER(?) AND fiscal_year IS NOT NULL
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
                WHERE UPPER(inst_name) = UPPER(?) {source_clause}
                AND pi_name IS NOT NULL AND pi_name != ''
                GROUP BY pi_name, source
                ORDER BY [Total ($M)] DESC""",
            conn, params=params,
        )
    return df


@st.cache_data(ttl=3600)
def get_institution_awards(inst_name: str, source: str | None = None,
                           fy: int | None = None) -> pd.DataFrame:
    clauses = ["UPPER(inst_name) = UPPER(?)"]
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
