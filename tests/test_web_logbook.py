"""The chart and logbook pages, end to end through the test client."""

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from glucobalance.models import CarbEntry, GlucoseReading, GlucoseTag, ReadingSource
from test_web import STEP1, onboard, saved_user, sign_up

WARSAW = ZoneInfo("Europe/Warsaw")


def set_up(client: TestClient) -> None:
    sign_up(client)
    onboard(client, {**STEP1, "monitoring_mode": "glucometer", "timezone": "Europe/Warsaw"})


def add_readings(engine: Engine, values: list[tuple[int, int, GlucoseTag | None]]) -> None:
    """Add (minutes ago, mg/dL, tag) readings for the only user."""
    session, user = saved_user(engine)
    with session:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        for minutes_ago, value, tag in values:
            session.add(
                GlucoseReading(
                    user=user,
                    measured_at=now - timedelta(minutes=minutes_ago),
                    value_mgdl=value,
                    source=ReadingSource.MANUAL,
                    tag=tag,
                )
            )
        session.commit()


def chart_data(html: str) -> dict:  # type: ignore[type-arg]
    match = re.search(r'<script id="chart-data" type="application/json">(.*?)</script>', html, re.S)
    assert match, "chart data missing"
    return json.loads(match.group(1))  # type: ignore[no-any-return]


# ---------- chart ----------


def test_chart_needs_login(client: TestClient) -> None:
    assert client.get("/chart", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/logbook", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/logbook.csv", follow_redirects=False).headers["location"] == "/login"


def test_daily_chart_embeds_the_figure_and_loads_plotly(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_readings(engine, [(1, 133, None)])
    page = client.get("/chart")
    assert page.status_code == 200
    assert "plotly" in page.text.lower()
    figure = chart_data(page.text)
    glucose = next(t for t in figure["data"] if t["name"] == "Glucose")
    assert glucose["y"] == [133]


def test_weekly_chart(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_readings(engine, [(10, 133, None), (60 * 24 * 3, 90, None)])
    figure = chart_data(client.get("/chart?view=week").text)
    readings = next(t for t in figure["data"] if t["name"] == "Readings")
    assert sorted(readings["y"]) == [90, 133]


def test_chart_can_show_another_day_and_view_names_fall_back(client: TestClient) -> None:
    set_up(client)
    assert client.get("/chart?day=2026-01-01").status_code == 200
    assert client.get("/chart?day=nonsense&view=nonsense").status_code == 200


def test_chart_has_previous_and_next_links(client: TestClient) -> None:
    set_up(client)
    page = client.get("/chart?day=2026-01-10").text
    assert "day=2026-01-09" in page
    assert "day=2026-01-11" in page


def test_chart_data_cannot_break_out_of_its_script_tag(client: TestClient, engine: Engine) -> None:
    set_up(client)
    session, user = saved_user(engine)
    with session:
        session.add(
            CarbEntry(
                user=user,
                eaten_at=datetime.now(UTC) - timedelta(minutes=5),
                grams=Decimal("30"),
                description="</script><script>alert(1)</script>",
            )
        )
        session.commit()
    assert "<script>alert(1)" not in client.get("/chart").text


# ---------- logbook ----------


def test_logbook_lists_entries_and_filters(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_readings(engine, [(10, 133, GlucoseTag.FASTING), (20, 99, GlucoseTag.BEDTIME)])
    page = client.get("/logbook")
    assert page.status_code == 200
    assert page.text.index("133 mg/dL") < page.text.index("99 mg/dL")  # newest first

    filtered = client.get("/logbook?tag=bedtime")
    assert "99 mg/dL" in filtered.text
    assert "133 mg/dL" not in filtered.text

    none = client.get("/logbook?type=carbs")
    assert "133 mg/dL" not in none.text
    assert "No entries" in none.text


def test_logbook_bad_filters_show_an_error(client: TestClient) -> None:
    set_up(client)
    response = client.get("/logbook?start=yesterday")
    assert response.status_code == 422
    assert "YYYY-MM-DD" in response.text


def test_logbook_pages(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_readings(engine, [(minute, 100 + minute, None) for minute in range(1, 61)])
    first = client.get("/logbook")
    assert "page=2" in first.text
    second = client.get("/logbook?page=2")
    assert "Page 2 of 2" in second.text


def test_csv_export_respects_the_filters(client: TestClient, engine: Engine) -> None:
    set_up(client)
    add_readings(engine, [(10, 133, GlucoseTag.FASTING), (20, 99, GlucoseTag.BEDTIME)])
    response = client.get("/logbook.csv?tag=fasting")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="glucobalance-logbook-' in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert len(lines) == 2
    assert ",133," in lines[1]


def test_csv_export_rejects_bad_filters(client: TestClient) -> None:
    set_up(client)
    assert client.get("/logbook.csv?start=yesterday").status_code == 422


def test_navigation_links_to_chart_and_logbook(client: TestClient) -> None:
    set_up(client)
    home = client.get("/").text
    assert 'href="/chart"' in home
    assert 'href="/logbook"' in home
