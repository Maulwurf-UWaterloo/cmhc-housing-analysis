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

1. **Ontario grew, Alberta retreated.** Ontario was the only major province
   to significantly increase housing starts April 2025→2026 (+25%,
   5,334→6,680 units), while Alberta posted the steepest decline
   (-40%, 5,294→3,192). Supply momentum is highly polarized at the
   provincial level.

2. **Ontario's growth is concentrated, not uniform.** Within Ontario,
   London surged +1,262% (71→967 units) while Kingston (-88%), Oshawa
   (-87%), and Hamilton (-86%) collapsed — suggesting supply is
   consolidating into select markets rather than spreading evenly.

3. **Higher vacancy is not translating to rent relief.** The top-right
   quadrant of the vacancy vs. rent-growth scatter is largely empty:
   CMAs with rising vacancy rates generally saw rent growth slow.
   Saguenay stands out as the tightest market (vacancy 1.3%, rent
   growth +10.9%), while Kelowna shows the opposite extreme
   (vacancy 6.4%, rent growth +2.4%).
   
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
