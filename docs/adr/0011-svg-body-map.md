# 0011. The body map is an inline SVG drawn from Python geometry

- Status: accepted
- Date: 2026-10-09

## Context

Stage 4 asks for a clickable body map with a usage heatmap. It must work on a phone, in the HTMX front end (ADR 0001), and stay testable without a browser.

## Decision

- **Inline SVG, rectangles only.** `bodymap.zone_box()` gives each site in `sitemap.SITES` a rectangle; a simple silhouette is drawn behind them. Front and back sit side by side and are mirrored as if looking at the person (their left is on your right from the front). Tests check that zones do not overlap and the mirroring is right.
- **Heat from the last 30 days.** Uses of any purpose are counted per site; `heat_level()` scales them to 0 to 4 against the most used site, shown as five shades. Blocked zones are red and dashed; the suggested next site has an amber outline. Every zone has a `<title>` with its name, state and count, for screen readers and hover.
- **Clicking a zone** loads a small panel with HTMX (`GET /sites/zone/{code}`): log a use for each of the user's rotations, mark it not available or available again, and set the preference. Without JavaScript the same link opens a full page. The panel posts to the existing `/sites` routes, so no rule is duplicated.

## Consequences

- No JavaScript chart or drawing library; the SVG is a template plus a dictionary of numbers.
- The drawing is schematic, not anatomical. A nicer outline can replace the silhouette later without touching the zones' codes.
- Adding a zone to the body map needs one row in `bodymap._LAYOUT`; a test fails if it is missing.

## Alternatives considered

- **An image with an HTML image map:** hard to colour per zone.
- **A JavaScript library (D3, a body-map widget):** more weight and a second way of building pages.
