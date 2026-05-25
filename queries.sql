-- Canadian Housing Market Analysis -- Sample SQL Queries
-- Demonstrates: JOIN, GROUP BY+AVG, RANK OVER PARTITION, LAG, CTE, HAVING
-- Run against housing.db: sqlite3 housing.db < queries.sql

-- ============================================================================
-- Q1. JOIN + GROUP BY + AVG
-- Provincial summary: total April 2026 starts vs avg vacancy / rent
-- ============================================================================
.print "Q1: Provincial summary"
.headers on
.mode column
SELECT
    g.province_code                    AS prov,
    COUNT(*)                           AS n_cmas,
    SUM(hs.total)                      AS total_starts_apr26,
    ROUND(AVG(rm.vacancy_rate), 2)     AS avg_vacancy_oct25,
    ROUND(AVG(rm.avg_rent_2br), 0)     AS avg_rent_oct25
FROM geography g
JOIN housing_starts hs ON hs.geo_id = g.geo_id AND hs.year = 2026
JOIN rental_market  rm ON rm.geo_id = g.geo_id AND rm.survey_date = 'Oct-25'
WHERE g.geo_type = 'CMA'
GROUP BY g.province_code
ORDER BY total_starts_apr26 DESC;

-- ============================================================================
-- Q2. Window function -- RANK CMAs within each province by starts
-- ============================================================================
.print "Q2: RANK starts within province (top 3 per province)"
WITH ranked AS (
    SELECT
        g.name,
        g.province_code,
        hs.total,
        RANK() OVER (PARTITION BY g.province_code ORDER BY hs.total DESC) AS rank_in_prov
    FROM geography g
    JOIN housing_starts hs ON hs.geo_id = g.geo_id AND hs.year = 2026
    WHERE g.geo_type = 'CMA'
)
SELECT name, province_code, total, rank_in_prov
FROM ranked
WHERE rank_in_prov <= 3
ORDER BY province_code, rank_in_prov;

-- ============================================================================
-- Q3. LAG -- YoY change in housing starts (April 2026 vs April 2025)
-- ============================================================================
.print "Q3: Biggest YoY drops in housing starts"
WITH yoy AS (
    SELECT
        g.name,
        g.province_code,
        hs.year,
        hs.total,
        LAG(hs.total) OVER (PARTITION BY g.geo_id ORDER BY hs.year) AS prev_year,
        hs.total - LAG(hs.total) OVER (PARTITION BY g.geo_id ORDER BY hs.year) AS yoy_change,
        ROUND(
            100.0 * (hs.total - LAG(hs.total) OVER (PARTITION BY g.geo_id ORDER BY hs.year))
            / LAG(hs.total) OVER (PARTITION BY g.geo_id ORDER BY hs.year), 1
        ) AS yoy_pct
    FROM geography g
    JOIN housing_starts hs ON hs.geo_id = g.geo_id
    WHERE g.geo_type = 'CMA'
)
SELECT name, province_code, prev_year AS apr_2025, total AS apr_2026, yoy_change, yoy_pct
FROM yoy
WHERE year = 2026 AND prev_year IS NOT NULL AND prev_year >= 100  -- filter noisy small markets
ORDER BY yoy_pct
LIMIT 10;

-- ============================================================================
-- Q4. CTE + HAVING -- "Loosening but still expensive" markets:
-- CMAs where vacancy is rising AND rent growth is still > 4%
-- ============================================================================
.print "Q4: Loosening markets with stubborn rent growth"
WITH oct25 AS (
    SELECT
        g.geo_id, g.name, g.province_code,
        rm.vacancy_rate,
        rm.yoy_rent_change
    FROM geography g
    JOIN rental_market rm ON rm.geo_id = g.geo_id
    WHERE rm.survey_date = 'Oct-25' AND g.geo_type = 'CMA'
)
SELECT name, province_code, vacancy_rate, yoy_rent_change
FROM oct25
WHERE vacancy_rate IS NOT NULL AND yoy_rent_change IS NOT NULL
GROUP BY name
HAVING vacancy_rate > 3.0 AND yoy_rent_change > 4.0
ORDER BY yoy_rent_change DESC;

-- ============================================================================
-- Q5. Multi-CTE -- Supply vs demand signal:
-- CMAs where 2026 starts dropped >20% YoY AND vacancy is still under 3%
-- (these are markets where construction is cooling but demand stays hot)
-- ============================================================================
.print "Q5: Cooling construction + tight rental market"
WITH starts_yoy AS (
    SELECT
        g.geo_id, g.name, g.province_code,
        hs.total AS starts_2026,
        LAG(hs.total) OVER (PARTITION BY g.geo_id ORDER BY hs.year) AS starts_2025
    FROM geography g
    JOIN housing_starts hs ON hs.geo_id = g.geo_id
    WHERE g.geo_type = 'CMA'
),
filtered AS (
    SELECT
        s.name, s.province_code, s.starts_2025, s.starts_2026,
        ROUND(100.0 * (s.starts_2026 - s.starts_2025) / s.starts_2025, 1) AS starts_yoy_pct,
        rm.vacancy_rate
    FROM starts_yoy s
    JOIN rental_market rm ON rm.geo_id = s.geo_id AND rm.survey_date = 'Oct-25'
    WHERE s.starts_2025 IS NOT NULL AND s.starts_2025 >= 100
)
SELECT *
FROM filtered
WHERE starts_yoy_pct < -20.0 AND vacancy_rate < 3.0
ORDER BY starts_yoy_pct;
