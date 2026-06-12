# PHIVOLCS Catalogue Capture Audit

**Status: PASS**

- Source: `Earthquake Catalogue of the Philippines.xlsx` (sha256 `e2a22971d6f98dfa...`)
- Generated: 2026-06-12T08:52:32.967366+00:00

## Counts
- Events in catalog.json: **3576**
- Features in catalog.geojson: **3576**
- Data rows found in xlsx: **3577**
- Per sheet: `1907-2018` = 3032, `2019-2025` = 545
- Non-empty cells seen in workbook: 38754 (widest row scanned: 1011 columns)
- Data cells reconciled 1:1 against events: 47046

## Partition proof
Every non-empty workbook cell was matched to exactly one of: preamble metadata, header metadata, or an event field. Unclaimed cells: **0**; metadata cells missing from workbook: **0**; cell/field mismatches: **0**.

## Anomaly ledger (asserted against known source)
- QA flags: {"mb_coerced_from_string": 1855, "ml_coerced_from_string": 1250, "invalid_datetime": 1}
- Invalid datetimes: [['2019-2025', 329]] (Hour=27 kept raw, datetime null)
- Preferred magnitude distribution: {"Ms": 1686, "Mb": 1035, "Ml": 446, "Mw": 409}
- Events with preferred mag < 5.0: 0
- Exact duplicate time+location pairs: 24

## Ranges
- Latitude: 2.0 to 22.0 degN
- Longitude: 116.3 to 133.0 degE
- Depth: 1.0 to 700.0 km
- Preferred magnitude: 5.0 to 8.3
- Years: 1907 to 2025

## Spot checks (first, last, 5 seeded-random)
- `PH-0001` 1907-2018 row 12: 1907-03-29T20:46:30Z lat 3.0 lon 122.0 depth 500.0 km M7.3 (Ms) flags=[]
- `PH-3577` 2019-2025 row 556: 2025-10-16T23:03:13Z lat 9.69 lon 126.22 depth 28.0 km M6.0 (Mw) flags=[]
- `PH-2620` 1907-2018 row 2631: 2011-02-15T07:18:17.620000Z lat 21.135 lon 121.186 depth 52.0 km M5.7 (Ms) flags=['ml_coerced_from_string', 'mb_coerced_from_string']
- `PH-0457` 1907-2018 row 468: 1967-04-22T17:27:51Z lat 8.27 lon 127.13 depth 84.0 km M5.0 (Mb) flags=['mb_coerced_from_string']
- `PH-0103` 1907-2018 row 114: 1934-09-06T02:16:52Z lat 6.5 lon 126.1 depth 150.0 km M6.0 (Ms) flags=[]
- `PH-3038` 2019-2025 row 17: 2019-01-24T08:34:53Z lat 19.17 lon 121.25 depth 27.0 km M5.5 (Ms) flags=[]
- `PH-1127` 1907-2018 row 1138: 1973-07-03T07:03:04.900000Z lat 12.21 lon 125.33 depth 33.0 km M6.5 (Mb) flags=['mb_coerced_from_string']

## Warnings
- 24 exact duplicate origin-time+location pairs: [('PH-0312', 'PH-0317'), ('PH-0313', 'PH-0318'), ('PH-0314', 'PH-0319'), ('PH-0315', 'PH-0320'), ('PH-0316', 'PH-0321')]

## Notes
- 1907-2018: 3032 data rows, all reconciled against events
- 2019-2025: 545 data rows, all reconciled against events
- events excluded below the M>=5.0 preamble floor: 1 (kept in metadata.excluded_events, capture-audited)
