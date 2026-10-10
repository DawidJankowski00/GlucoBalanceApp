# 0016. Analytics: consensus thresholds, rule-based patterns and a pure-Python PDF report

- Status: accepted
- Date: 2026-10-10

## Context

Stage 7 shows a user their patterns and prints a report for the diabetes clinic. The numbers must be explainable, because a clinician reads them and Stage 8 builds suggestions on top of them. The app runs on Windows, in Docker and in CI, and costs nothing to run.

## Decision

- **Statistics follow the international consensus on CGM metrics** (Battelino et al., 2019). Time in range uses the user's own target range; below range is under the low limit and above range is over the high limit. "Very low" (under 54 mg/dL) and "very high" (over 250 mg/dL) are fixed and counted inside below and above. Variability is the coefficient of variation (sample standard deviation over the mean, goal 36% or lower). GMI is `3.31 + 0.02392 × mean mg/dL`, shown as an estimate and never as a lab HbA1c.
- **Enough data.** A CGM period needs 14 days and at least 70% sensor coverage; coverage counts distinct 15-minute slots with a reading, so 5-minute and 15-minute sources compare fairly. Glucometer users have no coverage figure and get a warning under 2 readings a day. A warning never hides the numbers.
- **The AGP** folds all days onto one local clock in 15-minute buckets and draws the 5th, 25th, 50th, 75th and 95th percentiles (linear interpolation, like numpy's default). A bucket with fewer than 3 readings is skipped. CGM users get the AGP; glucometer users get the mean per part of the day (night, morning, afternoon, evening), because a few readings a day do not make percentile bands.
- **Pattern detectors are fixed rules** in `patterns.py`, with named thresholds: at least 3 different nights with a reading under 70 mg/dL between 00:00 and 06:00; the peak 1 to 3 hours after the first morning meal (05:00 to 11:00) above range on at least 3 days and at least half of the days that have data (4 days minimum); the first fasting value of the day (tagged fasting, or the first reading 05:00 to 08:00) above 130 mg/dL on at least half of at least 5 days. Each finding carries the readings that support it, so it can be checked by hand. Findings describe; they never say what to change.
- **Site performance** is the mean glucose 2 to 6 hours after each use, averaged per use and then per site, compared with the mean of all readings. A site is flagged after 3 counted uses when it is 15 mg/dL or more above that mean. Sensor placements are excluded because they do not deliver insulin. This is a hint, not a diagnosis: meals and exercise add noise.
- **Plain Python, not pandas.** The `statistics` module and a few loops are enough for thousands of points, and the code and tests stay small. pandas can come later if Stage 10 needs it.
- **The PDF is written with fpdf2**, a pure-Python library with no system dependencies. The AGP in the PDF is drawn natively from the same percentile numbers as the page, so no Plotly image export (and no headless browser) is needed. fpdf2's built-in fonts cover Latin-1 only, so text outside it (for example the Polish "ł") is transliterated rather than failing; bundling a Unicode font is a later step.
- The page and the PDF both call `build_analytics`, so they always show the same figures.

## Consequences

- Fixed thresholds cannot be tuned per user yet. They are named constants in one place, so changing them is a small edit plus tests.
- The PDF looks plainer than a browser-rendered page, and names with letters outside Latin-1 lose their accents.
- A user with a very high target range sees fewer "highs after breakfast" findings, because the rule uses their own range; the fasting goal stays fixed.

## Alternatives considered

- **WeasyPrint** (HTML to PDF): nicer layout from the same template, but it needs GTK system libraries that are painful on Windows and slim Docker images.
- **ReportLab:** mature, but a larger API, and its open-source edition adds licence questions for little gain.
- **Plotly image export (kaleido) for the AGP in the PDF:** needs a bundled browser; drawing from the numbers is simpler and testable.
- **scikit-learn or a statistical model for patterns:** harder to explain to a clinician, and Stage 7 only needs rules.
