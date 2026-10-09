# 0009. The body map is reference data defined in code

- Status: accepted
- Date: 2026-10-09

## Context

Site rotation (Stage 4) needs a fixed set of body sites: regions, sub-zones, front and back, left and right. The `body_sites` table already existed, but the demo seed script made up its own small layout, and nothing said which sites a real database should contain.

## Decision

- **One list in code:** `sitemap.SITES` is the only definition of the body map. Each region is described once for the left side and mirrored for the right, so the map is symmetric by construction (a test checks it).
- **A stable code per site:** `region-view-side-zone`, for example `abdomen-front-left-upper`. The code is unique and is what the SVG body map will use to find a zone. A new `zone` column holds the sub-zone name.
- **Loaded by a migration and by `seed_body_sites()`:** the migration inserts the missing sites, so a fresh database has the map without any extra step. `seed_body_sites()` does the same for tests and the demo seed, and is safe to run repeatedly. Existing rows are never changed, so ids stay stable.
- **Sensor sites are out of scope** until the CGM stage; the `CGM_SENSOR` purpose exists but no sensor-only zones are defined yet.

## Consequences

- Adding a zone means editing one tuple and writing a small migration that inserts it.
- The migration imports `SITES`, so it loads the map as it is at that revision of the code. A later change to the list needs its own migration rather than an edit to this one.
- Per-user data (blocked sites, preference weights, uses) stays in separate tables, not here.

## Alternatives considered

- **A database-only map (SQL inserts in the migration):** the app code would have no list to draw the SVG from.
- **A JSON or YAML data file:** one more format and parser for 24 rows.
