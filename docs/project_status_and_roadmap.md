# Federal Radar — Project Status & Roadmap

**Last updated:** 2026-05-26
**Status:** Data pipeline complete — API and UI layer is next

---

## 1. Current State

Federal Radar ingests federal award data from 9 sources into a single SQLite database.
The data pipeline, deduplication logic, and daily refresh scheduler are complete.
No front-end exists yet — the DB is queried directly for internal validation.

### Database Snapshot

| Source | Records | Total Funding | FY Range |
|---|---|---|---|
| NSF | 83,845 | $49.95B | FY2019–2026 |
| NIH | 453,631 | $223.13B | FY2019–2026 |
| DOD | 26,408 | $31.65B | FY2019–2026 |
| USDA | 27,276 | $18.38B | FY2019–2026 |
| NASA | 17,424 | $10.63B | FY2019–2026 |
| DOE | 10,395 | $24.43B | FY2019–2026 |
| Commerce | 6,749 | $11.55B | FY2019–2026 |
| EPA | 1,595 | $2.46B | FY2019–2026 |
| DHS | 150 | $0.32B | FY2019 only |
| **Total** | **627,473** | **$372.50B** | **FY2019–2026** |

---

## 2. Completed Milestones

| Milestone | Status |
|---|---|
| NSF bulk ZIP ETL | Complete |
| NSF incremental API sync | Complete |
| NIH RePORTER API fetcher | Complete |
| USASpending bulk download (7 agencies, FY2019–2026) | Complete |
| Parallel download execution | Complete |
| Crash-safe sentinel files | Complete |
| Multi-year award deduplication fix | Complete |
| Upsert: fiscal_year never overwritten | Complete |
| Upsert: awd_amount takes max (latest total) | Complete |
| APScheduler daily refresh (NSF + NIH) | Complete |
| Data governance test suite (NSF) | Complete (NSF only) |
| Railway deployment config | Complete |

---

## 3. Known Gaps & Issues

### Data Gaps
| Gap | Notes |
|---|---|
| DHS FY2020–2026 | Bulk download takes 20+ min/year on USASpending servers. FY2019 loaded (150 records). Run as overnight job when ready. |
| NIH amounts are per-year, not total | NIH `awd_amount` = one budget period slice. NSF and USASpending `awd_amount` = total award. Not directly comparable. See FUTURE_FEATURES.txt. |
| Test suite covers NSF only | `test_data_governance.py` and `baselines.json` need NIH and USASpending coverage added |

### Test Suite
The governance test suite (`tests/test_data_governance.py`) was written when only NSF
data existed. It needs updating to:
- Add NIH record count and funding baselines
- Add USASpending per-agency baselines
- Add cross-source consistency checks
- Update `VALID_DIRECTORATES` to include post-2022 NSF restructuring codes: `CSE`, `O/D`, `IRM`, `BFA`, `NSB`, `OCIO`

---

## 4. Recommended Additional Data Sources for VPRI Offices

These are publicly available federal sources not yet in the system. Prioritized by
relevance to university research offices.

### Tier 1 — High Priority (Major University Funders)

**Grants.gov (Opportunities API)**
- What: Open federal grant solicitations (FOAs, RFPs, NOFAs) — the forward-looking "radar"
- Why critical: This is WHERE opportunities are posted before awards are made. Currently we only track awards after the fact. Adding Grants.gov turns Federal Radar into an actual opportunity alert system.
- API: `https://apply07.grants.gov/grantsws/rest/opportunities/search/`
- Data: Agency, CFDA number, open/close dates, eligibility, synopsis
- Source type: Opportunities, not awards — different schema needed

**Department of Education (ED)**
- What: Higher Education Act programs, FIPSE, research competitions, TRIO, GEAR UP
- Why: Direct university funder — Title IV, graduate research, HBCU/MSI programs
- Source: USASpending bulk download (agency = "Department of Education")
- Easy add: Same pipeline as existing agencies, just add ED to AGENCIES dict

**Department of Transportation (DOT)**
- What: University Transportation Centers (UTC) program, research grants
- Why: UTC is a flagship university R&D program, ~$75M/year to university consortia
- Source: USASpending bulk download (agency = "Department of Transportation")
- Easy add: Same pipeline

**Health and Human Services — Non-NIH (HRSA, AHRQ, SAMHSA, ACF)**
- What: Health workforce research (HRSA), health services research (AHRQ), substance abuse (SAMHSA), social services (ACF)
- Why: Large funding stream often missed because people think "HHS = NIH only"
- Source: USASpending bulk download (agency = "Department of Health and Human Services")
- Note: Need to exclude NIH records to avoid double-counting

**National Endowment for the Humanities (NEH)**
- What: Humanities research, digital humanities, preservation
- Why: Critical for universities with strong humanities programs — often invisible in STEM-focused grant dashboards
- Source: USASpending bulk download (agency = "National Endowment for the Humanities")
- Easy add: Same pipeline, low volume

### Tier 2 — Valuable for Comprehensive Coverage

**SBIR/STTR (sbir.gov)**
- What: Small business R&D awards — but many flow through university spin-offs, tech transfer, and faculty startups
- Why: Technology transfer offices and innovation centers track these closely
- API: `https://api.sbir.gov/public/api/`
- Note: Separate schema needed — company-focused, not institution-focused

**Department of Justice (DOJ)**
- What: Criminology, forensics, cybersecurity, public policy research
- Why: Significant funder for social science and law school research
- Source: USASpending bulk download

**USAID**
- What: International development research, global health, food security
- Why: Large funder for universities with international programs
- Source: USASpending bulk download

**Department of Veterans Affairs (VA)**
- What: Biomedical and health research, mental health, rehabilitation
- Why: VA research is heavily university-partnered; often under-tracked
- Source: USASpending bulk download

### Tier 3 — Specialized / Future Consideration

**National Endowment for the Arts (NEA)**
- Small but relevant for arts and design programs

**FEMA / Emergency Management**
- Hazard mitigation and resilience research — growing post-climate awareness

**IARPA (Intelligence Advanced Research Projects Activity)**
- Cutting-edge CS, social science, and neuroscience research
- Included in DOD/intelligence community USASpending data

**Private Foundations (Future — Phase 3)**
- Gates Foundation, Mellon, MacArthur, Sloan, Simons, Moore
- NOT in federal systems — requires separate integrations or partnerships
- Candid (Foundation Directory) has an API but requires paid subscription

---

## 5. Phase Roadmap

### Phase 1 — Internal VPR Validation (Current)
- [x] Data pipeline (NSF, NIH, 7 USASpending agencies)
- [x] Data model correctness (deduplication, fiscal_year, amounts)
- [ ] Fix test suite to cover NIH + USASpending
- [ ] Add ED, DOT, HHS-non-NIH to USASpending pipeline (easy adds)
- [ ] Update docs to current state (this file)

### Phase 2 — Internal Tool (Query + Search)
- [ ] REST API layer (FastAPI or Flask) — search by institution, agency, FY, keyword
- [ ] Basic internal dashboard — table view, filters, export to CSV
- [ ] Grant detail page with source permalink
- [ ] Grants.gov opportunity feed (forward-looking alerts)
- [ ] Fix NIH amount labeling in UI

### Phase 3 — Pilot to Other Institutions
- [ ] Multi-institution support (institution filter as first-class concept)
- [ ] Benchmarking — compare institution vs. peer institutions
- [ ] Opportunity alerts / email digest
- [ ] User accounts and saved searches
- [ ] Private foundation data (Candid API or equivalent)

---

## 6. Technical Reference

For detailed technical decisions and the reasoning behind them, see `CONTEXT.md`.
For deferred features, see `FUTURE_FEATURES.txt`.
