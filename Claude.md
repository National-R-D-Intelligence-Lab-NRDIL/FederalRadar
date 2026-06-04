## Project Vision and Context

This is not a hobby project. This is PRISM — a research intelligence
platform targeting university research offices nationally. Every
engineering decision must support a product that could serve 300+
institutions at $150K-$200K/year.

## What This Tool Answers
One question for a VPR on Monday morning:
"In [agency/program], where are peers beating us and by how much?"

## Non-Negotiable Principles
- Data accuracy over speed — wrong numbers destroy trust permanently
- Federal fiscal year (Oct 1 – Sep 30) is the standard — never calendar year
- Obligation date is the award received date — not project start date
- UEI is the cross-source deduplication key — never match on name alone
- raw_json is preserved on every record — source truth is never lost
- One unified awards table — source column distinguishes agencies

## Current Data State
- NSF: 83,845 awards FY2019-2026 via bulk ZIP + daily API
- NIH: 156,439 awards FY2019-2026 via RePORTER API + deduplication
- USASpending: ED, DOD, DOE, NASA, USDA, Commerce, DOT, NEH, EPA, DHS
- Total: 410,797 awards · $503B · 12 agencies
- institutions table: UEI-keyed, canonical names, peer flags

## Peer Lists (official UNT institutional lists)
Texas: UT Austin, Texas A&M, UT Arlington, UT Dallas, UTRGV, UTEP,
UTSA, University of Houston, Texas Tech, Texas State

National: Arizona State, Georgia State, UCF, Purdue, UC Riverside,
UIC, University of Utah, USF, University of Memphis, Tulane

## Dashboard Pages Built
1. Home — Competitive Gap Analysis (scorecard, gap table, heatmap, Sankey, PDF export)
2. Portfolio Risk — agency concentration, what-if scenarios, peer diversification
3. Expiring Awards — funding cliff, PI impact, CSV export
4. Action Dashboard — cross-agency money movement (YTD apples-to-apples),
   "How Does UNT Compare?" table, peer missed opportunities, lapsed capacity
5. Data Dictionary — agency abbreviations, field definitions, planned agencies, peer sets

## What Still Needs Building
- Data governance disclaimer and freshness bar on every page
- PDF export polish
- Daily automated refresh via APScheduler (NSF + NIH)
- USASpending ED filter — exclude CARES Act formula grants
- Streamlit UI refinement per approved mockups

## Product Architecture
- This repo = Federal Radar (component 1 of PRISM)
- PRISM is the unified platform combining Federal Radar + HERD + CI Sponsor Guide
- Build Federal Radar as a standalone product that can eventually be integrated
- No integration with HERD or CI Sponsor Guide in this repo yet

## How to Approach Every Task

Before writing any code, always:
1. State the problem in one sentence
2. List 2-3 possible approaches with tradeoffs — time, complexity, maintainability
3. Recommend one with a reason
4. Ask for approval before proceeding

Never start coding without approval on the approach.

## Performance Rules
- Batch database operations — never insert one record at a time
- Always use indexes for queries on large tables
- Paginate API calls — never assume one page is enough
- Use generators for large file processing — never load entire file into memory
- Commit transactions in batches of 500-1000, not per record

## Efficiency Rules
- Estimate record count and time before running any bulk operation
- If a loop will run more than 10,000 iterations, propose a set-based alternative first
- Never use a Python loop where a single SQL query works
- Always test with 100 records before running on full dataset

## Before Running Anything
- State what the script will do
- State how many records it will touch
- State estimated runtime
- Ask for confirmation if runtime exceeds 2 minutes

## Response Style
- Short and precise
- No explanations unless asked
- No code unless approach is approved
- Show options, wait for decision

## Data Integrity Rules
- Never make assumptions about data — always run a query first
- Never state a number, coverage percentage, or data characteristic without verifying it against the actual database
- Never guess — if uncertain, say "I don't know, let me check" and run the query
- Always look at the data before drawing conclusions
- State only facts that are backed by query results
- Always test new SQL against the live DB before writing the query function — catch edge cases early
- When comparing fiscal years, always account for partial-year bias — never compare a full FY to a partial FY without matching the time window

## Streamlit Patterns
- All query functions go in `app/queries.py` — pages import from there
- Always use `@st.cache_data(ttl=3600)` on query functions
- Always use `_conn()` for database connections (sets PRAGMA cache, mmap)
- Pages live in `app/pages/` with numeric prefix for sidebar ordering
- Use `pd.read_sql_query()` for DataFrames, `conn.execute().fetchone()` for scalars
- Use Plotly for charts, `st.dataframe()` for tables — never matplotlib
- Pandas 3.x — use `.style.map()` not `.style.applymap()` (removed)

## UI/UX Rules
- Never take screenshots to show the user — they have the browser open
- The audience is a VPR, not a data scientist — labels must be plain English
- Always show dollar amounts in $M with 1-2 decimal places
- Always show fiscal years as integers, never with thousands separator (2025, not 2,025)
- Color convention: green = good/growing, red = bad/shrinking, gray = neutral/absent
- Every data table should have a one-line summary above it (e.g., "Your peers won $318M across 129 programs...")

## Before Every Task
- Read Claude.md first
- Confirm the approach matches the rules here before starting any work
