# Canadian Housing Market Analysis

Cross-sectional analysis of Canadian housing supply and rental market
indicators by Census Metropolitan Area (CMA), using CMHC open data.

**Stack:** Python (pandas) · SQLite · SQL (window functions, CTEs)

---

## Data sources

Two CMHC publications:

- **Monthly Housing Starts (April 2026)** — Single-detached vs all-others
  starts for ~46 CMAs and 10 provinces, current month + YoY comparison.
- **Rental Market Report (Canada, 2025)** — Vacancy rate, turnover rate,
  average 2-bedroom rent, and YoY rent change for the same CMAs,
  comparing Oct-2024 to Oct-2025.

Both files are publicly available at
[cmhc-schl.gc.ca](https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/housing-data/data-tables).

---

## Schema

Three tables in `housing.db`:

```
geography (geo_id, name, geo_type ['Province'|'CMA'], province_code)
housing_starts (geo_id, year, single_detached, all_others, total)
rental_market (geo_id, survey_date, vacancy_rate, turnover_rate,
               avg_rent_2br, yoy_rent_change)
```

40 CMAs join cleanly across both fact tables.

---

## Running

```bash
pip install -r requirements.txt
python etl.py            # builds housing.db
python -c "import sqlite3; conn=sqlite3.connect('housing.db'); \
           [print(r) for r in conn.execute(open('queries.sql').read())]"
```

---

## Findings

<!-- TODO: Fill in concrete numbers and 3-5 charts after running the analysis -->

1. **[Finding 1]** — e.g., "Ontario accounts for X% of all housing starts
   but has the Y-highest avg vacancy at Z%."

2. **[Finding 2]** — e.g., "5 of 10 BC CMAs show 'loosening but expensive'
   pattern: vacancy > 3% AND YoY rent growth > 4%."

3. **[Finding 3]** — e.g., "Halifax's April 2026 starts collapsed 78.6%
   YoY (916 → 196), but vacancy is still 2.7% — a supply-shock signal."

---

## Known limitations

- Ottawa-Gatineau CMA spans both Ontario and Quebec. CMHC's rental survey
  publishes separate values for the Ontario and Quebec portions; this
  pipeline drops those split rows and keeps only the combined housing-starts
  entry, which carries no `province_code`.
- Charlottetown CA appears in rental data but not in housing starts
  (population threshold), so it is rental-only.
- Quality indicators (a/b/c/d) from the rental file are dropped during
  ingestion to keep the schema flat. CMHC suppression markers (`**`, `++`)
  become `NULL`.
