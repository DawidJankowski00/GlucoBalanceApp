# Architecture Decision Records

An ADR is a short note recording one significant decision: what was decided, why, and what the alternatives were. Add a new file for each decision, numbered in order (`0002-...md`). Do not rewrite old ones; supersede them with a new ADR.

Use [0000-template.md](0000-template.md) as a starting point.

| ADR | Decision |
|---|---|
| [0001](0001-fastapi-htmx.md) | FastAPI + HTMX instead of a React front end |
| [0002](0002-sqlalchemy-alembic-repositories.md) | SQLAlchemy 2, Alembic and a repository layer for persistence |
| [0003](0003-simglucose-optional-and-python-312.md) | simglucose as an optional dependency group, Python pinned to 3.12 |
| [0004](0004-session-cookie-login.md) | Signed session cookie for login, Argon2 for passwords |
| [0005](0005-settings-change-log.md) | One service writes settings and logs every change |
| [0006](0006-utc-storage-and-user-time-zone.md) | Store times in UTC, read and show them in the user's time zone |
| [0007](0007-plotly-charts-and-csv-export.md) | Plotly charts built in Python, and a CSV export that guards against formulas |
| [0008](0008-food-search-favourites-and-hypo-log.md) | Food search behind an adapter with a cache, favourite meals and the hypo log |
| [0009](0009-body-map-as-code-reference-data.md) | The body map is reference data defined in code and loaded by a migration |
| [0010](0010-site-blocks-weights-and-rotations.md) | Site blocks with an optional end date, preference weights, and one rotation per purpose |
| [0011](0011-svg-body-map.md) | The body map is an inline SVG drawn from Python geometry, with a 30-day heatmap |
| [0012](0012-reminder-rules-and-apscheduler.md) | Reminder rules as pure functions, and APScheduler with a database job store |
| [0013](0013-web-push-and-notification-centre.md) | Web Push with VAPID keys, and an in-app notification centre as the fallback |
