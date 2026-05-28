"""
phase4_canonical_names.py
Rebuild institutions table (now includes NIH), re-apply peer flags,
and populate inst_canonical_name on all awards records.
Safe to re-run.
"""

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "federal_awards.db"

# Peer flags confirmed across all sessions
PEER_FLAGS = [
    # (inst_uei, is_my_institution, is_peer_texas, is_peer_national, peer_label)
    ("G47WN1XZNWX9", 1, 0, 0, "University of North Texas"),
    ("JSV3KA8HHBB5", 1, 0, 0, "University of North Texas"),
    ("JF6XLNB4CDJ5", 0, 1, 0, "Texas A&M University"),
    ("MG1PPMPNS9G3", 0, 1, 0, "UT Austin"),
    ("V6AFQPN18437", 0, 1, 0, "UT Austin"),
    ("LMLUKUPJJ9N3", 0, 1, 0, "UT Arlington"),
    ("EJCVPNN1WFS5", 0, 1, 0, "UT Dallas"),
    ("U44ZMVYU52U6", 0, 1, 0, "UTSA"),
    ("C1DEGMMKC7W7", 0, 1, 0, "UTEP"),
    ("L3ATVUT2KNK7", 0, 1, 0, "UTRGV"),
    ("HS5HWWK1AAU5", 0, 1, 0, "Texas State University"),
    ("EGLKRQ5JBCZ7", 0, 1, 0, "Texas Tech University"),
    ("D7Q8JLAJU3M4", 0, 1, 0, "University of Houston"),
    ("QKWEF8XLMTT3", 0, 1, 0, "University of Houston"),
    ("NTLHJXM55KZ6", 0, 0, 1, "Arizona State University"),
    ("YRXVL4JYCEF5", 0, 0, 1, "Purdue University"),
    ("MNS7B9CVKDN7", 0, 0, 1, "Georgia State University"),
    ("SNQ6M7S6TK89", 0, 0, 1, "Georgia State University"),
    ("NKAZLXLL7Z91", 0, 0, 1, "University of South Florida"),
    ("RD7MXJV7DKT9", 0, 0, 1, "UCF"),
    ("LL8GLEVH6MG3", 0, 0, 1, "University of Utah"),
    ("F2VSMAKDH8Z7", 0, 0, 1, "University of Memphis"),
    ("W8XEAJDKMXH3", 0, 0, 1, "University of Illinois Chicago"),
    ("XNY5ULPU8EN6", 0, 0, 1, "Tulane University"),
]

# UC Riverside — confirmed from NIH API
UC_RIVERSIDE_UEI = "MR5QC5FCAVH5"


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # -- Step 1: Rebuild institutions table -----------------------------------
    print("Step 1: Rebuilding institutions table...")
    conn.execute("DROP TABLE IF EXISTS institutions")
    conn.execute("""
        CREATE TABLE institutions (
            inst_uei            TEXT PRIMARY KEY,
            canonical_name      TEXT NOT NULL,
            inst_state_code     TEXT,
            uei_source          TEXT DEFAULT 'awards',
            is_my_institution   INTEGER DEFAULT 0,
            is_peer_texas       INTEGER DEFAULT 0,
            is_peer_national    INTEGER DEFAULT 0,
            peer_label          TEXT,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    t0 = time.time()
    conn.execute("""
        INSERT INTO institutions (inst_uei, canonical_name, inst_state_code)
        SELECT inst_uei, inst_name AS canonical_name, inst_state_code
        FROM (
            SELECT
                inst_uei,
                inst_name,
                inst_state_code,
                ROW_NUMBER() OVER (
                    PARTITION BY inst_uei
                    ORDER BY COUNT(*) DESC, inst_name ASC
                ) AS rn
            FROM awards
            WHERE inst_uei IS NOT NULL AND inst_uei != ''
              AND inst_name IS NOT NULL AND inst_name != ''
            GROUP BY inst_uei, inst_name
        )
        WHERE rn = 1
    """)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]
    print(f"  {count:,} institutions built in {time.time()-t0:.1f}s")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_uei ON institutions(inst_uei)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_canonical ON institutions(canonical_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_state ON institutions(inst_state_code)")
    conn.commit()

    # -- Step 2: Re-apply peer flags ------------------------------------------
    print("\nStep 2: Applying peer flags...")
    applied = 0
    for uei, is_mine, is_tx, is_nat, label in PEER_FLAGS:
        exists = conn.execute(
            "SELECT 1 FROM institutions WHERE inst_uei=?", (uei,)
        ).fetchone()
        if exists:
            conn.execute("""
                UPDATE institutions
                SET is_my_institution=?, is_peer_texas=?, is_peer_national=?, peer_label=?
                WHERE inst_uei=?
            """, (is_mine, is_tx, is_nat, label, uei))
            applied += 1
        else:
            # Insert stub (peer not in awards data yet)
            conn.execute("""
                INSERT INTO institutions (inst_uei, canonical_name, is_my_institution,
                    is_peer_texas, is_peer_national, peer_label)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (uei, label, is_mine, is_tx, is_nat, label))
            applied += 1
            print(f"  Inserted stub for {label} ({uei})")

    # UC Riverside — national peer
    conn.execute("""
        UPDATE institutions SET is_peer_national=1, peer_label='UC Riverside'
        WHERE inst_uei=?
    """, (UC_RIVERSIDE_UEI,))

    conn.commit()
    print(f"  {applied} peer flags applied")

    # Verify peers
    rows = conn.execute("""
        SELECT inst_uei, peer_label, is_my_institution, is_peer_texas, is_peer_national
        FROM institutions
        WHERE is_my_institution=1 OR is_peer_texas=1 OR is_peer_national=1
        ORDER BY is_my_institution DESC, is_peer_texas DESC, peer_label
    """).fetchall()
    print(f"\n  Confirmed peers in institutions table ({len(rows)} rows):")
    for uei, label, mine, tx, nat in rows:
        tag = "MY" if mine else ("TX" if tx else "NAT")
        print(f"    [{tag}] {uei}  {label}")

    # -- Step 3: Populate inst_canonical_name on awards -----------------------
    print("\nStep 3: Populating inst_canonical_name on awards...")
    t0 = time.time()
    result = conn.execute("""
        UPDATE awards
        SET inst_canonical_name = (
            SELECT canonical_name FROM institutions
            WHERE institutions.inst_uei = awards.inst_uei
        )
        WHERE inst_uei IS NOT NULL
    """)
    conn.commit()
    print(f"  {result.rowcount:,} records updated in {time.time()-t0:.1f}s")

    # Coverage report
    row = conn.execute("""
        SELECT COUNT(*), COUNT(inst_canonical_name), COUNT(*)-COUNT(inst_canonical_name)
        FROM awards
    """).fetchone()
    print(f"\n  inst_canonical_name coverage: {row[1]:,}/{row[0]:,} ({row[1]/row[0]*100:.1f}%)")
    print(f"  Still missing (no UEI):        {row[2]:,}")

    # Spot check deduplication
    print("\nSpot check — UNT across sources:")
    rows = conn.execute("""
        SELECT source, inst_name, inst_uei, inst_canonical_name, COUNT(*) as cnt
        FROM awards
        WHERE inst_uei IN ('G47WN1XZNWX9', 'JSV3KA8HHBB5')
        GROUP BY source, inst_name
        ORDER BY source
    """).fetchall()
    for source, name, uei, canonical, cnt in rows:
        print(f"  {source:<12} {name:<45} -> {canonical}  ({cnt} awards)")

    conn.close()
    print("\nPhase 4 complete.")


if __name__ == "__main__":
    run()
