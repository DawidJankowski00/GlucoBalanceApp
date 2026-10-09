# 0007. Plotly charts built in Python, and a CSV export that guards against formulas

- Status: accepted
- Date: 2026-10-09

## Context

Stage 3 adds a daily and weekly glucose chart with a target band, and a logbook that can be exported as CSV. Stage 7 will need more charts (time in range, the ambulatory glucose profile), so the library choice is reused. The app is server-rendered with HTMX (ADR 0001), so there is no front-end build step.

## Decision

- **Plotly.js** draws the charts in the browser, loaded from a CDN as the small `plotly.js-basic-dist-min` bundle (scatter, bar and shapes only), pinned to a version. The Python `plotly` package is not installed.
- **The figure is built in Python** (`charts.py`) as a plain dict with times as local wall-clock strings and values in the user's display unit, embedded in the page as JSON (`|tojson`, which escapes `<`, `>` and `&`, so a note cannot close the script tag). The browser only calls `Plotly.newPlot`. This keeps the chart's numbers (time zone, mmol/L conversion, the band, the axis range) unit-tested; only the drawing is untested.
- Insulin and carbs sit in a separate strip under the glucose plot (a second y axis) so their labels never collide with the glucose line.
- The library is loaded on demand by the chart page, not in `<head>`, because HTMX boosted navigation swaps only the body.
- **CSV export** (`logbook.py`) uses the standard `csv` module. It writes the stored mg/dL value, the value in the display unit and the unit, with times in both UTC and local time, oldest first. Any text cell (a note or description) that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading `'`, so a spreadsheet shows it as text instead of running it as a formula.
- The logbook range is capped at one year, and a page shows 50 entries.

## Consequences

- The chart needs the CDN at view time. Self-hosting the file is a later option if the app has to work offline.
- Hover text and legends are Plotly defaults and are not covered by tests.
- The formula guard changes a note such as `-2` to `'-2` in the CSV. That is the accepted cost of a safe export.

## Alternatives considered

- **Chart.js:** smaller, but no ready-made band, shapes or percentile areas, which Stage 7 needs.
- **Server-rendered SVG:** no JavaScript, but no hover or zoom, and more code to maintain.
- **The Python `plotly` package:** builds the same dict, but adds a large dependency for no gain here.
