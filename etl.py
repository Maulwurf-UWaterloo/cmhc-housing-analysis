"""
CMHC Housing Market ETL
-----------------------
Loads two CMHC Excel files into a SQLite database:
  1. Monthly Housing Starts (housing-starts-tables-2026-04-en.xlsx)
  2. Rental Market Report (rmr-canada-2025-en.xlsx)

Outputs: housing.db (SQLite) with 3 tables:
  - geography:     CMA + province dimension table
  - housing_starts: April 2026 starts by single-detached / all others / total
  - rental_market: Oct-24 vs Oct-25 vacancy / turnover / rent / YoY rent change

Run from the directory containing the two .xlsx files:
    python etl.py
"""

import sqlite3
from pathlib import Path

import pandas as pd

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
HOUSING_STARTS_FILE = "monthly-housing-starts-tables-2026-04-en.xlsx"
RENTAL_MARKET_FILE = "rmr-canada-2025-en.xlsx"
DB_FILE = "housing.db"

# Province abbreviation -> (full name, 2-letter code)
PROVINCE_MAP = {
    "N.L.": ("Newfoundland and Labrador", "NL"),
    "P.E.I.": ("Prince Edward Island", "PE"),
    "N.S.": ("Nova Scotia", "NS"),
    "N.B.": ("New Brunswick", "NB"),
    "Que.": ("Québec", "QC"),
    "Ont.": ("Ontario", "ON"),
    "Man.": ("Manitoba", "MB"),
    "Sask.": ("Saskatchewan", "SK"),
    "Alta.": ("Alberta", "AB"),
    "B.C.": ("British Columbia", "BC"),
}

# Rental file uses full names (sometimes with accents); map to 2-letter code.
PROVINCE_NAME_TO_CODE = {full: code for full, code in PROVINCE_MAP.values()}

# Regional aggregates to skip (not real geographies for our analysis)
REGIONAL_AGGREGATES = {"Atlantic", "Prairies", "Canada", "Total"}

# Manual CMA name overrides where housing-starts naming differs from rental
# Maps the housing-starts name to the normalized form (which we'll also use
# for rental after stripping its "CMA"/"CA" suffix).
CMA_NAME_OVERRIDES = {
    # housing: "Greater/Grand Sudbury" vs rental: "Greater Sudbury/Grand Sudbury"
    "Greater/Grand Sudbury": "Greater Sudbury/Grand Sudbury",
    # housing: "Ottawa-Gatineau" (single row, plus indented Gatineau/Ottawa);
    # rental splits into Ontario part + Quebec part. We keep the combined
    # entry for housing and drop the indented Gatineau/Ottawa sub-rows.
    # Rental side is handled below by skipping the "(Qué./Ont. part)" rows
    # OR keeping them as separate entities -- we choose to keep as separate.
}

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def clean_number(value):
    """Convert a cell to float, treating CMHC suppression markers as None."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        s = value.strip()
        if s in ("##", "**", "++", "-", ""):
            return None
        # Strip thousands separators ("1,209" -> "1209")
        s = s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return float(value)


def clean_int(value):
    f = clean_number(value)
    return int(f) if f is not None else None


def normalize_cma(name):
    """Strip ' CMA' / ' CA' suffix and apply overrides."""
    n = name.strip()
    # Strip suffixes
    for suffix in (" CMA", " CA"):
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
            break
    return n


# -----------------------------------------------------------------------------
# Parsers
# -----------------------------------------------------------------------------
def parse_housing_starts(path):
    """
    Returns a DataFrame with columns:
      name, geo_type ('Province' or 'CMA'), province_code (for CMAs: None
        until we cross-reference; for provinces: the 2-letter code),
      year, single_detached, all_others, total
    Each (name, year) is a row; year is 2025 or 2026 for the April snapshot.
    """
    df = pd.read_excel(path, sheet_name="Table 1", header=None)
    records = []
    in_metropolitan = False

    for idx in range(7, len(df)):
        raw_area = df.iat[idx, 0]
        if pd.isna(raw_area):
            continue
        raw_area = str(raw_area)
        # Detect indented sub-rows BEFORE stripping (housing-starts uses
        # two leading spaces for "  Gatineau" / "  Ottawa" under Ottawa-Gatineau)
        is_indented = raw_area.startswith(" ") or raw_area.startswith("\t")
        area = raw_area.strip()
        if not area:
            continue

        # Section header
        if area == "Metropolitan Areas":
            in_metropolitan = True
            continue

        # Skip footer rows
        if area.startswith("1 Data for") or area.startswith("Source:"):
            break

        # Skip regional aggregates
        if area in REGIONAL_AGGREGATES:
            continue

        # Skip indented Ottawa-Gatineau sub-rows ("  Gatineau", "  Ottawa")
        if is_indented:
            continue

        # Read 2025 and 2026 values
        sd_25, sd_26 = clean_int(df.iat[idx, 2]), clean_int(df.iat[idx, 3])
        ao_25, ao_26 = clean_int(df.iat[idx, 5]), clean_int(df.iat[idx, 6])
        tot_25, tot_26 = clean_int(df.iat[idx, 8]), clean_int(df.iat[idx, 9])

        if not in_metropolitan:
            # Provinces use abbreviations like "N.L." or "P.E.I.    "
            key = area.rstrip()
            if key not in PROVINCE_MAP:
                continue
            full_name, code = PROVINCE_MAP[key]
            geo_type = "Province"
            normalized = full_name
            province_code = code
        else:
            # CMA
            geo_type = "CMA"
            normalized = CMA_NAME_OVERRIDES.get(area, area)
            province_code = None  # filled in later via CMA -> province lookup

        records.append(
            {
                "name": normalized,
                "geo_type": geo_type,
                "province_code": province_code,
                "year": 2025,
                "single_detached": sd_25,
                "all_others": ao_25,
                "total": tot_25,
            }
        )
        records.append(
            {
                "name": normalized,
                "geo_type": geo_type,
                "province_code": province_code,
                "year": 2026,
                "single_detached": sd_26,
                "all_others": ao_26,
                "total": tot_26,
            }
        )

    return pd.DataFrame(records)


def parse_rental_market(path):
    """
    Returns a DataFrame with columns:
      name, geo_type, province_code,
      survey_date ('Oct-24' or 'Oct-25'),
      vacancy_rate, turnover_rate, avg_rent_2br, yoy_rent_change
    """
    df = pd.read_excel(path, sheet_name="Table 1.0", header=None)
    records = []
    current_province_code = None

    for idx in range(7, len(df)):
        centre = df.iat[idx, 0]
        if pd.isna(centre):
            continue
        centre = str(centre).strip()
        if not centre:
            continue

        # Footer
        if centre.startswith("§") or centre.startswith("Quality") or centre.startswith("Source:"):
            break

        # Province row: ends with "10,000+"
        if centre.endswith("10,000+"):
            province_name = centre.replace("10,000+", "").strip()
            current_province_code = PROVINCE_NAME_TO_CODE.get(province_name)
            if current_province_code is None:
                continue  # unknown province
            geo_type = "Province"
            normalized = province_name
            province_code = current_province_code
        elif centre.startswith("Canada"):
            # Skip "Canada 10,000+" and "Canada CMAs" national rows
            continue
        elif "(Qué. part)" in centre or "(Ont. part)" in centre:
            # Skip Ottawa-Gatineau split rows -- housing-starts has them
            # combined as "Ottawa-Gatineau", so the split versions can't join.
            continue
        else:
            # CMA row
            geo_type = "CMA"
            normalized = normalize_cma(centre)
            province_code = current_province_code  # inherit from preceding province

        # Read the 4 quartet groups
        # Vacancy: cols 1 (Oct-24), 3 (Oct-25)
        # Turnover: cols 6 (Oct-24), 8 (Oct-25)
        # Avg Rent 2BR: cols 11 (Oct-24), 13 (Oct-25)
        # YoY % change: cols 15 (Oct-23->24), 17 (Oct-24->25)
        rec_24 = {
            "name": normalized,
            "geo_type": geo_type,
            "province_code": province_code,
            "survey_date": "Oct-24",
            "vacancy_rate": clean_number(df.iat[idx, 1]),
            "turnover_rate": clean_number(df.iat[idx, 6]),
            "avg_rent_2br": clean_int(df.iat[idx, 11]),
            "yoy_rent_change": clean_number(df.iat[idx, 15]),
        }
        rec_25 = {
            "name": normalized,
            "geo_type": geo_type,
            "province_code": province_code,
            "survey_date": "Oct-25",
            "vacancy_rate": clean_number(df.iat[idx, 3]),
            "turnover_rate": clean_number(df.iat[idx, 8]),
            "avg_rent_2br": clean_int(df.iat[idx, 13]),
            "yoy_rent_change": clean_number(df.iat[idx, 17]),
        }
        records.append(rec_24)
        records.append(rec_25)

    return pd.DataFrame(records)


# -----------------------------------------------------------------------------
# Schema + Load
# -----------------------------------------------------------------------------
SCHEMA_SQL = """
DROP TABLE IF EXISTS housing_starts;
DROP TABLE IF EXISTS rental_market;
DROP TABLE IF EXISTS geography;

CREATE TABLE geography (
    geo_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    geo_type      TEXT    NOT NULL CHECK (geo_type IN ('Province', 'CMA')),
    province_code TEXT,
    UNIQUE(name, geo_type)
);

CREATE TABLE housing_starts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    geo_id          INTEGER NOT NULL REFERENCES geography(geo_id),
    year            INTEGER NOT NULL,
    single_detached INTEGER,
    all_others      INTEGER,
    total           INTEGER,
    UNIQUE(geo_id, year)
);

CREATE TABLE rental_market (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    geo_id           INTEGER NOT NULL REFERENCES geography(geo_id),
    survey_date      TEXT    NOT NULL,
    vacancy_rate     REAL,
    turnover_rate    REAL,
    avg_rent_2br     INTEGER,
    yoy_rent_change  REAL,
    UNIQUE(geo_id, survey_date)
);

CREATE INDEX idx_starts_geo  ON housing_starts(geo_id);
CREATE INDEX idx_rental_geo  ON rental_market(geo_id);
"""


def build_geography(starts_df, rental_df):
    """Union the (name, geo_type) pairs from both sources into one dim table."""
    cols = ["name", "geo_type", "province_code"]
    combined = pd.concat([starts_df[cols], rental_df[cols]], ignore_index=True)
    # Drop duplicates on (name, geo_type), keeping the first non-null province
    combined = (
        combined.sort_values("province_code", na_position="last")
        .drop_duplicates(subset=["name", "geo_type"], keep="first")
        .reset_index(drop=True)
    )
    return combined


def load_to_sqlite(starts_df, rental_df, geography_df, db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)
    conn.commit()

    # Insert geography
    for _, row in geography_df.iterrows():
        cur.execute(
            "INSERT INTO geography (name, geo_type, province_code) VALUES (?, ?, ?)",
            (row["name"], row["geo_type"], row["province_code"]),
        )

    # Map (name, geo_type) -> geo_id
    cur.execute("SELECT geo_id, name, geo_type FROM geography")
    geo_lookup = {(name, t): gid for gid, name, t in cur.fetchall()}

    # Insert housing starts
    inserted_starts = 0
    for _, row in starts_df.iterrows():
        key = (row["name"], row["geo_type"])
        if key not in geo_lookup:
            continue
        cur.execute(
            """INSERT INTO housing_starts
               (geo_id, year, single_detached, all_others, total)
               VALUES (?, ?, ?, ?, ?)""",
            (
                geo_lookup[key],
                int(row["year"]),
                row["single_detached"],
                row["all_others"],
                row["total"],
            ),
        )
        inserted_starts += 1

    # Insert rental market
    inserted_rental = 0
    for _, row in rental_df.iterrows():
        key = (row["name"], row["geo_type"])
        if key not in geo_lookup:
            continue
        cur.execute(
            """INSERT INTO rental_market
               (geo_id, survey_date, vacancy_rate, turnover_rate,
                avg_rent_2br, yoy_rent_change)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                geo_lookup[key],
                row["survey_date"],
                row["vacancy_rate"],
                row["turnover_rate"],
                row["avg_rent_2br"],
                row["yoy_rent_change"],
            ),
        )
        inserted_rental += 1

    conn.commit()
    conn.close()
    return inserted_starts, inserted_rental


# -----------------------------------------------------------------------------
# Verification queries (sanity check)
# -----------------------------------------------------------------------------
VERIFY_SQL = """
SELECT
    g.name                            AS cma,
    g.province_code                   AS prov,
    hs.total                          AS starts_apr_2026,
    rm.vacancy_rate                   AS vacancy_oct_2025,
    rm.avg_rent_2br                   AS rent_2br_oct_2025,
    rm.yoy_rent_change                AS rent_yoy_change_pct
FROM geography g
JOIN housing_starts hs ON hs.geo_id = g.geo_id AND hs.year = 2026
JOIN rental_market  rm ON rm.geo_id = g.geo_id AND rm.survey_date = 'Oct-25'
WHERE g.geo_type = 'CMA'
ORDER BY hs.total DESC
LIMIT 15;
"""


def run_verification(db_path):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(VERIFY_SQL, conn)
    conn.close()
    return df


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    base = Path(__file__).parent
    starts_path = base / HOUSING_STARTS_FILE
    rental_path = base / RENTAL_MARKET_FILE

    print(f"Reading housing starts from {starts_path.name} ...")
    starts_df = parse_housing_starts(starts_path)
    print(f"  -> {len(starts_df)} rows ({starts_df['name'].nunique()} unique geographies)")

    print(f"Reading rental market from {rental_path.name} ...")
    rental_df = parse_rental_market(rental_path)
    print(f"  -> {len(rental_df)} rows ({rental_df['name'].nunique()} unique geographies)")

    print("Building geography dimension ...")
    geography_df = build_geography(starts_df, rental_df)
    print(f"  -> {len(geography_df)} unique geographies "
          f"({(geography_df['geo_type'] == 'CMA').sum()} CMAs, "
          f"{(geography_df['geo_type'] == 'Province').sum()} provinces)")

    print(f"Writing to {DB_FILE} ...")
    n_starts, n_rental = load_to_sqlite(starts_df, rental_df, geography_df, base / DB_FILE)
    print(f"  -> {n_starts} housing_starts rows, {n_rental} rental_market rows")

    print("\nSanity check (top 15 CMAs by 2026 housing starts, joined with rental):")
    print("-" * 80)
    result = run_verification(base / DB_FILE)
    print(result.to_string(index=False))

    # Coverage report
    print("\nJoin coverage report:")
    print("-" * 80)
    conn = sqlite3.connect(base / DB_FILE)
    starts_cmas = pd.read_sql(
        "SELECT DISTINCT g.name FROM geography g "
        "JOIN housing_starts hs ON hs.geo_id = g.geo_id "
        "WHERE g.geo_type = 'CMA'", conn)["name"].tolist()
    rental_cmas = pd.read_sql(
        "SELECT DISTINCT g.name FROM geography g "
        "JOIN rental_market rm ON rm.geo_id = g.geo_id "
        "WHERE g.geo_type = 'CMA'", conn)["name"].tolist()
    conn.close()

    starts_only = set(starts_cmas) - set(rental_cmas)
    rental_only = set(rental_cmas) - set(starts_cmas)
    both = set(starts_cmas) & set(rental_cmas)

    print(f"  CMAs in BOTH (joinable): {len(both)}")
    print(f"  CMAs in housing_starts only: {len(starts_only)}")
    if starts_only:
        print(f"    {sorted(starts_only)}")
    print(f"  CMAs in rental_market only: {len(rental_only)}")
    if rental_only:
        print(f"    {sorted(rental_only)}")


if __name__ == "__main__":
    main()
